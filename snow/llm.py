"""
The two LLM passes of the daily run, through the Claude API (SDK `anthropic`, key ANTHROPIC_API_KEY; model
SNOW_MODEL, default claude-opus-5). Both return structured JSON (output_config.format) and never fit numbers:

  extract(date, products, obs, layers)  -> observations as records, weak-layer snapshots, model notes
  brief(date, summary, ledger, products) -> the day's brief per zone and an overview, from the ledger and the
                                            model's state summary (never from yesterday's brief)

Without a key nothing is called and the daily run goes on without these. Inputs are trimmed to INPUT_CHARS.
"""
import json
import os

from snow.state import CLASSES

MODEL = os.environ.get("SNOW_MODEL", "claude-opus-5")
INPUT_CHARS = 400_000
SURFACE = CLASSES + ["unknown"]
STATUS = ["active", "dormant", "healed"]
BANDS = ["below", "near", "above"]
ASPECTS = ["N", "NE", "E", "SE", "S", "SW", "W", "NW", "all"]

EXTRACT_SCHEMA = {
    "type": "object", "additionalProperties": False,
    "required": ["observations", "layers", "notes"],
    "properties": {
        "observations": {"type": "array", "items": {
            "type": "object", "additionalProperties": False,
            "required": ["source", "source_id", "obs_date", "location", "lat", "lon", "zone", "elevation_ft", "band", "aspects", "surface", "confidence", "quote"],
            "properties": {
                "source": {"type": "string", "enum": ["nac_obs", "nwac_product", "trip", "other"]},
                "source_id": {"type": "string"},
                "obs_date": {"type": "string"},
                "location": {"type": "string"},
                "lat": {"type": ["number", "null"]}, "lon": {"type": ["number", "null"]},
                "zone": {"type": ["string", "null"]},
                "elevation_ft": {"type": ["number", "null"]},
                "band": {"type": ["string", "null"], "enum": BANDS + [None]},
                "aspects": {"type": "array", "items": {"type": "string", "enum": ASPECTS}},
                "surface": {"type": "string", "enum": SURFACE},
                "confidence": {"type": "number"},
                "quote": {"type": "string"}}}},
        "layers": {"type": "array", "items": {
            "type": "object", "additionalProperties": False,
            "required": ["name", "status", "zones", "bands", "buried", "last", "evidence", "summary"],
            "properties": {
                "name": {"type": "string"}, "status": {"type": "string", "enum": STATUS},
                "zones": {"type": "array", "items": {"type": "string"}},
                "bands": {"type": "array", "items": {"type": "string", "enum": BANDS}},
                "buried": {"type": ["string", "null"]}, "last": {"type": "string"},
                "evidence": {"type": "array", "items": {"type": "string"}},
                "summary": {"type": "string"}}}},
        "notes": {"type": "array", "items": {
            "type": "object", "additionalProperties": False,
            "required": ["text", "evidence"],
            "properties": {"text": {"type": "string"}, "evidence": {"type": "array", "items": {"type": "string"}}}}}}}

BRIEF_SCHEMA = {
    "type": "object", "additionalProperties": False,
    "required": ["overview", "zones", "notes"],
    "properties": {
        "overview": {"type": "string"},
        "zones": {"type": "array", "items": {
            "type": "object", "additionalProperties": False,
            "required": ["zone", "headline", "text"],
            "properties": {"zone": {"type": "string"}, "headline": {"type": "string"}, "text": {"type": "string"}}}},
        "notes": {"type": "array", "items": {
            "type": "object", "additionalProperties": False,
            "required": ["text", "evidence"],
            "properties": {"text": {"type": "string"}, "evidence": {"type": "array", "items": {"type": "string"}}}}}}}

EXTRACT_SYSTEM = """You read avalanche-center forecast products and public field observations for the Washington Cascades and
Olympics and turn them into structured records for a snow-surface model that predicts ski conditions (powder, wind
effect, sun and rain crusts, melt-freeze). You do not forecast and you do not invent: every record quotes the text it
came from, and anything the text does not say is null. Surface classes: """ + ", ".join(CLASSES) + """ (unknown when
the text does not describe the surface). Elevation bands: below / near / above treeline. Persistent weak layers are
tracked by the name the forecasters use (usually the date it was buried, e.g. "Dec 12 facets"): match today's
mentions to the known layers you are given, keep their names, and add a snapshot only for layers mentioned today
or whose status changed. Notes are for things a rule-based model would miss (e.g. "east-slope zones crusted faster
than the sun alone explains, three reports"), each with the product or observation ids as evidence."""

BRIEF_SYSTEM = """You write the daily snow-conditions brief for backcountry skiers in the Washington Cascades and Olympics from
three inputs: the model's state summary (class fractions by zone, elevation band and aspect), the ledger of dated
observations, weak layers and notes from the last weeks, and today's forecast bottom lines. Say where the good snow
is likely and why, by zone, band and aspect; say what is uncertain and what would settle it; never restate yesterday's
brief (you are not given it), never give avalanche advice beyond quoting the center's danger and bottom line, and
keep every zone to a few sentences. Plain language, no hype, specific aspects and elevations."""


def client():
    if not os.environ.get("ANTHROPIC_API_KEY"):
        return None
    import anthropic
    return anthropic.Anthropic()


def _trim(obj, limit=INPUT_CHARS):
    s = json.dumps(obj, separators=(",", ":"), default=str)
    return s if len(s) <= limit else s[:limit] + "...[truncated]"


def call(system, user, schema, log=print, max_tokens=16000):
    """one structured request; the parsed JSON, or None (no key, refusal, truncation, bad JSON)"""
    c = client()
    if c is None:
        log("llm: no ANTHROPIC_API_KEY, skipped")
        return None
    r = c.messages.create(model=MODEL, max_tokens=max_tokens, system=system,
                          messages=[{"role": "user", "content": user}],
                          output_config={"format": {"type": "json_schema", "schema": schema}})
    if r.stop_reason == "refusal":
        log("llm: refused (%s)" % getattr(getattr(r, "stop_details", None), "category", None))
        return None
    if r.stop_reason == "max_tokens":
        log("llm: output truncated at %d tokens" % max_tokens)
        return None
    text = next((b.text for b in r.content if b.type == "text"), "")
    try:
        out = json.loads(text)
    except ValueError as e:
        log("llm: bad JSON: %r" % e)
        return None
    u = getattr(r, "usage", None)
    if u is not None:
        log("llm: %s in %d out %d tokens" % (MODEL, u.input_tokens, u.output_tokens))
    return out


def extract(date, products, obs, layers, log=print):
    user = ("Date: %s\n\nKnown weak layers (latest snapshot each):\n%s\n\nToday's forecast products (raw JSON from avalanche.org):\n%s\n\n"
            "Today's public observations (raw JSON, may be empty):\n%s\n\nProduce the records." % (date, _trim(layers, 40_000), _trim(products), _trim(obs)))
    return call(EXTRACT_SYSTEM, user, EXTRACT_SCHEMA, log)


def brief(date, summary, ledger_recent, bottom_lines, log=print):
    user = ("Date: %s\n\nModel state summary (zones -> bands -> aspects -> class fractions, classes %s):\n%s\n\n"
            "Ledger, last weeks (observations, residuals, layers, notes):\n%s\n\nToday's forecast bottom lines by zone:\n%s\n\nWrite the brief."
            % (date, ", ".join(CLASSES), _trim(summary, 120_000), _trim(ledger_recent, 150_000), _trim(bottom_lines, 60_000)))
    return call(BRIEF_SYSTEM, user, BRIEF_SCHEMA, log)
