"""Tests for harvesters factory and detail page HTML parsing."""

from pipeline.sources import get_harvester, list_harvesters, JambHarvester, WaecHarvester


def test_harvester_registry():
    harvesters = list_harvesters()
    assert "jamb" in harvesters
    assert "waec" in harvesters

    jamb_h = get_harvester("jamb")
    assert isinstance(jamb_h, JambHarvester)
    assert jamb_h.supported_exams == ["JAMB"]

    waec_h = get_harvester("waec")
    assert isinstance(waec_h, WaecHarvester)
    assert waec_h.supported_exams == ["WAEC"]


def test_jamb_detail_parser():
    sample_html = """
    <html>
      <body>
        <h1 class="text-xl"><p>Which of the following is a scalar quantity?</p></h1>
        <div class="flex gap-6 items-center rounded-lg px-4 border py-2 bg-[#DFFFEC]">
          <div class="flex items-center gap-6">
            <span class="uppercase font-medium">a</span>
            <p class="font-medium">Energy</p>
          </div>
        </div>
        <div class="flex gap-6 items-center rounded-lg px-4 border py-2">
          <div class="flex items-center gap-6">
            <span class="uppercase font-medium">b</span>
            <p class="font-medium">Force</p>
          </div>
        </div>
        <div class="flex gap-6 items-center rounded-lg px-4 border py-2">
          <div class="flex items-center gap-6">
            <span class="uppercase font-medium">c</span>
            <p class="font-medium">Velocity</p>
          </div>
        </div>
        <div class="flex gap-6 items-center rounded-lg px-4 border py-2">
          <div class="flex items-center gap-6">
            <span class="uppercase font-medium">d</span>
            <p class="font-medium">Acceleration</p>
          </div>
        </div>
      </body>
    </html>
    """
    harvester = JambHarvester()
    payload = harvester._parse_detail(
        html_text=sample_html,
        qid="998877",
        detail_url="https://myschool.ng/classroom/physics/998877?exam_type=utme&exam_year=2025",
        subject="physics",
        year=2025,
    )
    assert payload is not None
    assert payload.stem == "Which of the following is a scalar quantity?"
    assert len(payload.options) == 4
    assert payload.reported_answer == "a"
    assert payload.options[0].text == "Energy"
    assert payload.options[1].text == "Force"
