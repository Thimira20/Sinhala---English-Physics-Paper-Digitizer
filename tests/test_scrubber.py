"""
Tests for core.scrubber: blacklist removal, phone scrubbing, url/email scrubbing,
page markers, and verification that numbers inside LaTeX equations are never removed.
"""
from core.models import Settings
from core.scrubber import scrub

def test_scrubber_preserves_math_equations():
    settings = Settings(
        branding_blacklist=["Samitha Ratnayake"],
        scrub_phone_numbers=True,
        scrub_urls_emails=True
    )
    
    input_md = (
        "ගුරුත්වය යටතේ චලිතය Samitha Ratnayake විසින් සකසන ලදී.\n"
        "සමීකරණය $v = u + 0771234567 t$ සහ $s = 071-987-6543 t + \\frac{1}{2} a t^2$ වේ.\n"
        "සම්බන්ධ වන්න: 077 123 4567 හෝ test@physics.lk\n"
        "- 4 -\n"
        "අවසාන වේගය $v = 10\\text{ m s}^{-1}$ වේ."
    )
    
    cleaned, removed = scrub(input_md, settings)
    
    # Brand name removed
    assert "Samitha Ratnayake" not in cleaned
    # Plain text phone number removed
    assert "077 123 4567" not in cleaned
    assert "test@physics.lk" not in cleaned
    assert "- 4 -" not in cleaned
    
    # CRITICAL: Numbers inside math equations MUST BE PRESERVED
    assert "$v = u + 0771234567 t$" in cleaned
    assert "$s = 071-987-6543 t + \\frac{1}{2} a t^2$" in cleaned
    assert "$v = 10\\text{ m s}^{-1}$" in cleaned
    assert len(removed) > 0

def test_blacklist_whitespace_tolerance():
    settings = Settings(branding_blacklist=["Innovative Physics"])
    text = "මෙය Innovative    Physics ආයතනයේ නිබන්ධනයකි."
    cleaned, removed = scrub(text, settings)
    assert "Innovative" not in cleaned
    assert "Physics" not in cleaned
    assert "ආයතනයේ නිබන්ධනයකි." in cleaned
