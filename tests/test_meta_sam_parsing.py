"""Parsing of real SAM 3.1 wire output (sample from the official
meta-sam-parser README), without any network calls."""
import json

from PIL import Image

from backend.app.services.sam_service import (MetaSAMBackend, collect_output_text,
                                              parse_sam_output)

SAMPLE = (
    "<0f>0<|box;x1=211;y1=228;x2=270;y2=254;w=320;h=334;c=0.91|>"
    "<|mask;x=0;y=0;c=0.91;data=27,60,~!!!!M!0c[0o91w?q1!pIH4pPRVp2B3'7`e.ioeAf6-k/#Xd8%dX9x(|>"
    ",1<|box;x1=155;y1=228;x2=202;y2=254;w=320;h=334;c=0.42|>"
    "<|mask;x=0;y=0;c=0.42;data=27,48,~!!!!J!0c[q=Pj_zs=*4C4(/./x#:/`S_GnD`=o3?X{emCgO$y@|>\n"
)


def sse(chunks, final=None):
    lines = [f"data: {json.dumps({'type': 'response.output_text.delta', 'delta': c})}" for c in chunks]
    if final is not None:
        lines.append("data: " + json.dumps({"type": "response.content_part.done",
                                            "part": {"type": "output_text", "text": final}}))
    lines.append("data: " + json.dumps({"type": "response.completed"}))
    return lines


def test_collect_output_text_from_deltas_split_mid_mask():
    cut = SAMPLE.index("Pj_z")  # split inside a mask payload
    assert collect_output_text(sse([SAMPLE[:cut], SAMPLE[cut:]])) == SAMPLE


def test_collect_output_text_prefers_final_part():
    assert collect_output_text(sse(["garbled"], final=SAMPLE)) == SAMPLE


def test_parse_sam_output_polygons_in_source_pixels():
    masks = parse_sam_output(SAMPLE, "rooftop")
    assert len(masks) == 2
    m0 = masks[0]
    xs = [p[0] for p in m0.polygon]
    ys = [p[1] for p in m0.polygon]
    assert 211 <= min(xs) and max(xs) <= 271 and 228 <= min(ys) and max(ys) <= 255
    assert abs(m0.score - 0.91) < 1e-6


def test_confidence_filter_and_empty_output():
    assert len(parse_sam_output(SAMPLE, "rooftop", min_confidence=0.5)) == 1
    assert parse_sam_output("", "rooftop") == []


def test_backend_payload_and_segment(monkeypatch):
    be = MetaSAMBackend(api_key="test")
    img = Image.new("RGB", (320, 334))
    body = be.payload(img, "rooftop")
    content = body["input"][0]["content"]
    assert body["model"] == "sam-3.1"
    assert content[0] == {"type": "input_text", "text": "rooftop"}
    assert content[1]["image_url"].startswith("data:image/jpeg;base64,")
    calls = []
    monkeypatch.setattr(be, "call", lambda image, prompt: calls.append(prompt) or SAMPLE)
    out = be.segment(img, ["rooftop", "garbage pile"])
    assert calls == ["rooftop", "garbage pile"]  # one request per concept
    assert len(out) == 4 and {m.prompt for m in out} == {"rooftop", "garbage pile"}
