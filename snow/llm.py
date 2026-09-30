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
MOISTURE = ["dry", "moist", "wet"]
WIND_EFFECT = ["none", "light", "heavy"]
TIERS = ["center_product", "pro_obs", "public_obs", "trip"]
GRAINS = ["SH", "FC", "DH", "MFcr", "IFrc", "PP", "DF", "RG"]      # CAAML grain codes, NWAC's layer ids use them lowercased

EXTRACT_SCHEMA = {
    "type": "object", "additionalProperties": False,
    "required": ["observations", "layers", "notes"],
    "properties": {
        "observations": {"type": "array", "items": {
            "type": "object", "additionalProperties": False,
            "required": ["source", "source_id", "obs_date", "location", "lat", "lon", "zone", "elevation_ft", "band", "aspects", "surface",
                         "moisture", "wind_effect", "spatial_precision_m", "source_tier", "confidence", "quote"],
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
                "moisture": {"type": ["string", "null"], "enum": MOISTURE + [None]},
                "wind_effect": {"type": ["string", "null"], "enum": WIND_EFFECT + [None]},
                "spatial_precision_m": {"type": ["number", "null"]},
                "source_tier": {"type": "string", "enum": TIERS},
                "confidence": {"type": "number"},
                "quote": {"type": "string"}}}},
        "layers": {"type": "array", "items": {
            "type": "object", "additionalProperties": False,
            "required": ["name", "status", "zones", "bands", "buried", "grain", "last", "evidence", "summary"],
            "properties": {
                "name": {"type": "string"}, "status": {"type": "string", "enum": STATUS},
                "zones": {"type": "array", "items": {"type": "string"}},
                "bands": {"type": "array", "items": {"type": "string", "enum": BANDS}},
                "buried": {"type": ["string", "null"]}, "grain": {"type": ["string", "null"], "enum": GRAINS + [None]},
                "last": {"type": "string"},
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
the text does not describe the surface). Beside the class, record what the text says separately: `moisture` (dry,
moist, wet), `wind_effect` (none, light, heavy; "wind-affected but still soft" is light wind_effect with a soft
class), each null when not stated. Elevation bands: below / near / above treeline.
`spatial_precision_m` says how well the report is placed: about 100 when the text gives coordinates or a probe or
pit site, 300 for a named slope, run or ridge, 1500 for a named place, drainage or pass, null when only the zone is
known. `source_tier`: center_product for a forecast product or other center writing; pro_obs for an observation by a
professional observer, guide, patroller or forecaster (say so in the text or the observer field); public_obs for any
other public observation; trip for Chris's own trip log. `confidence` is your confidence that the surface class is
what the text describes at that place: lower it for hedged phrasing ("may", "possibly", "reportedly", "likely",
second-hand accounts) and for reports that name only a zone.
Persistent weak layers are tracked by the name the forecasters use (usually the date it was buried, e.g. "Dec 12
facets") plus `buried` (ISO date) and `grain` (CAAML code: """ + ", ".join(GRAINS) + """) when known; buried date and
grain make the layer's key (like NWAC's own layer ids, 20220130_fcsf), so "Jan 30 facets" and "the late-January
facet-crust sandwich" resolve to one layer. Match today's mentions to the known layers you are given, keep their
names, dates and grains, and add a snapshot only for layers mentioned today or whose status changed. Notes are for
things a rule-based model would miss (e.g. "east-slope zones crusted faster than the sun alone explains, three
reports"), each with the product or observation ids as evidence."""

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
    from snow.score import places
    names = ", ".join(sorted(places()))
    user = ("Known place names (use one of these in `location` when the report is at or near it, else the report's own words): %s\n\n" % names) + ("Date: %s\n\nKnown weak layers (latest snapshot each):\n%s\n\nToday's forecast products (raw JSON from avalanche.org):\n%s\n\n"
            "Today's public observations (raw JSON, may be empty):\n%s\n\nProduce the records." % (date, _trim(layers, 40_000), _trim(products), _trim(obs)))
    return call(EXTRACT_SYSTEM, user, EXTRACT_SCHEMA, log)


def brief(date, summary, ledger_recent, bottom_lines, log=print):
    user = ("Date: %s\n\nModel state summary (zones -> bands -> aspects -> class fractions, classes %s):\n%s\n\n"
            "Ledger, last weeks (observations, residuals, layers, notes):\n%s\n\nToday's forecast bottom lines by zone:\n%s\n\nWrite the brief."
            % (date, ", ".join(CLASSES), _trim(summary, 120_000), _trim(ledger_recent, 150_000), _trim(bottom_lines, 60_000)))
    return call(BRIEF_SYSTEM, user, BRIEF_SCHEMA, log)
