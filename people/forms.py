import re
from django import forms

# Existing postal-address heuristics; account email is not collected by intake.
_STREET_SUFFIX = (
    r"(?:St|Street|Ave|Avenue|Rd|Road|Blvd|Boulevard|Dr|Drive|Ln|Lane|"
    r"Ct|Court|Pl|Place|Way|Ter|Terrace|Cir|Circle|Sq|Square|"
    r"Hwy|Highway|Pkwy|Parkway|Trl|Trail|Aly|Alley|Bnd|Bend|"
    r"Br|Branch|Brk|Break|Byp|Bypass|Cmp|Camp|Cmn|Common|"
    r"Cres|Crescent|Cv|Cove|Cvte|Coven|Clf|Cliff|Clb|Club|"
    r"Cyn|Canyon|Dmn|Domain|Esd|Estate|Est|Estate|Expy|Expressway|"
    r"Fl|Flat|Fls|Flats|Fur|Furlong|Gal|Gallery|Glen|Grv|Grove|"
    r"Hbr|Harbor|Hgts|Heights|Hll|Hill|Hlws|Hills|Hp|Hope|"
    r"Is|Island|Isl|Island|Knl|Knoll|Ky|Key|Lk|Lake|Lck|Lock|"
    r"Lgt|Light|Lnd|Land|Lndg|Landing|Lw|Lawn|Lwng|Lawn|Mall|"
    r"Mnr|Manor|Mdws|Meadows|Mdwe|Meadow|Mss|Mission|Mt|Mountain|"
    r"Mtn|Mountain|Nck|Neck|Pd|Pad|Pk|Park|Pke|Parkway|Plz|Plaza|"
    r"Pnt|Point|Pr|Prairie|Prt|Port|Rbg|Ridge|Rdg|Ridge|"
    r"Rv|River|Rva|Riva|Rvrs|Rivers|Rvrt|River|Rte|Route|"
    r"Shl|Shell|Shls|Shells|Shp|Ship|Shpg|Shipping|Slp|Slope|"
    r"Slps|Slopes|Sme|Summer|Smt|Summit|Spr|Spring|Sprng|Spring|"
    r"Stw|Stream|Stwn|Station|Tce|Terrace|Tcr|Terrace|Trm|Term|"
    r"Trms|Terms|Twp|Township|Vw|View|Vge|Village|Vlg|Village|"
    r"Wlk|Walk|Wks|Works|Wld|World|Yd|Yard|Yds|Yards)"
)
POSTAL_PATTERNS = [
    re.compile(r"^\d{1,6}\s+[A-Za-z\s]{2,}\s+" + _STREET_SUFFIX + r"\.?\s*$", re.IGNORECASE),
    re.compile(r"^\d{1,6}\s+[A-Za-z\s]{2,}\s+" + _STREET_SUFFIX, re.IGNORECASE),
    re.compile(r"\b\d{5}(?:-\d{4})?\b"),
    re.compile(r"\bPO\s*\.?\s*Box\s*\d+", re.IGNORECASE),
    re.compile(r"\b(?:Apt|Suite|Unit|Ste)\s+\d+", re.IGNORECASE),
    re.compile(r"^\d+\s+\w+.*,\s*\w+.*,\s*[A-Z]{2}\s+\d{5}"),
    re.compile(r"\b(?:Rt|Route|Hwy|Highway)\s+\d+", re.IGNORECASE),
    re.compile(r"\b(?:Floor|Level)\s+\d+", re.IGNORECASE),
]


def has_postal_address(text: str) -> bool:
    if not text:
        return False
    return any(pattern.search(text) for pattern in POSTAL_PATTERNS)


PIRATE_MAIL_DESCRIPTION = (
    'A public-ish facing place where you can be found — a bar, a band, a '
    'bistro, a camp, a club, a karaoke night, a bookstore, a venue, a '
    'volunteer group, a nonprofit, an art circle, a family, an entourage, '
    'an institution. Mail reaches you by finding someone there who knows '
    'you. No postal addresses.'
)


class RequestALetterForm(forms.Form):
    """Public request intake; contact email belongs to accounts."""
    nickname = forms.CharField(max_length=255, label='Name or Alias', widget=forms.TextInput(attrs={'placeholder': 'What should we call you?'}))
    pirate_address = forms.CharField(max_length=255, label='Pirate Mail Address', help_text=PIRATE_MAIL_DESCRIPTION, widget=forms.TextInput(attrs={'placeholder': '[Name a Place, no addresses]'}))
    pirate_place_kind = forms.CharField(max_length=32, required=False, label='Place Kind', widget=forms.TextInput(attrs={'placeholder': ''}))
    city = forms.CharField(max_length=255, required=False, label='City/State', widget=forms.TextInput(attrs={'placeholder': 'City/State'}))
    write_about = forms.CharField(widget=forms.Textarea(attrs={'rows': 3, 'placeholder': 'A topic of your choice, a question, a dream, a hobby. What are you requesting?'}), required=False, label='What should someone write to you about?')
    override = forms.BooleanField(required=False, label='I confirm this is a Pirate Mail address (not a postal address)')
    override_comment = forms.CharField(
        widget=forms.Textarea(attrs={'rows': 3}), required=False,
        label='Explain why this is a Pirate Mail address',
        help_text="Describe the place and how someone would find you there. Example: 'This is a bar called Main Street — we host a weekly open mic and the owner knows me.'",
    )

    def clean(self):
        data = super().clean()
        pirate_addr = (data.get('pirate_address') or '').strip()
        override = data.get('override', False)
        override_comment = (data.get('override_comment') or '').strip()
        if has_postal_address(pirate_addr):
            if not override:
                self.add_error(
                    'pirate_address',
                    "Postal address detected. This field must be a Pirate Mail "
                    "address — a social place where you can be found "
                    "(bar, camp, venue, bookstore, band, etc.)<br><br>"
                    "<strong>To fix:</strong> either change your address to a "
                    "place name (e.g. 'The Rusty Nail Bar'), OR check the "
                    "override box below and explain in the comment box why "
                    "your place name is actually a pirate mail address "
                    "(e.g. 'This is a bar called Main Street — we host a "
                    "weekly open mic and the owner knows me').",
                )
            elif not override_comment:
                self.add_error(
                    'override_comment',
                    "You checked the override box but left the explanation "
                    "box empty. Please describe the place and how someone "
                    "would find you there. Example: 'This is a bar called "
                    "Main Street — we host a weekly open mic and the owner "
                    "knows me.'",
                )
        return data
