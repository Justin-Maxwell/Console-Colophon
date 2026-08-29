#!/usr/bin/env python3
"""The identicon as text: two lines, for clients that render neither an image
nor ANSI colour. A terminal chat client shows an assistant message as plain
markdown -- an inline PNG arrives as literal base64 and ANSI escapes are
stripped -- but Unicode block glyphs and colour emoji survive.

    <cell><cell><cell>
    <cell><cell><cell> <emoji><emoji><emoji>

The two parts have names, and they are the names of the artifacts each one is
written to. The pattern is drawn on a **lattice** -- `sextant` on the 2x3 set,
`octant` on the 2x4 -- three characters by two lines either way, carrying the
whole 5x5 grid. The **tricolour** is the colour: three emoji squares. The
tricolour terminates the mark rather than opening it, because an emoji is a
full character cell tall and so sits flush beside the line that is full of
grid.

Both lattices are written. They differ in how tall the mark stands and in how
likely a font is to have the glyphs, not in what they can carry, so which one
suits is the host's question rather than this file's. `text` draws sextants
unless told otherwise.

No key, no digest and no palette of its own: `text` takes a grid and a colour,
so this file can be vendored alone into a tool with no identicon machinery.

    python3 text-identicon.py '#2692d9' '.#.#.,.#.#.,#...#,#.#.#,.#.#.'

Standard library only.
"""

import itertools
import math

# ---------------------------------------------------------------------------
# The two lattices
#
# Both put the 5x5 grid in three characters by two lines, and both are
# lossless: every one of the ten pinned vectors reconstructs its grid exactly
# from either. `work-in-progress/lattice-comparison.md` is the two side by side
# on real keys.
#
# Neither is a fallback for the other and both are written, because what
# separates them is the host, not the mark:
#
#   octants   2x4. Unicode 16.0, 2024. Squarer -- a terminal cell is roughly
#             twice as tall as it is wide, so a 2x4 subcell is about square,
#             and five rows span 1.25 cell-heights.
#   sextants  2x3. Unicode 13.0, 2020, so a font is four years likelier to have
#             them, and a host without the glyphs draws the whole mark as tofu.
#             Five rows span 1.67 cell-heights, a third taller for the same
#             width.
#
# Bit i of a pattern is subcell (row i // 2, col i % 2), rows top to bottom, in
# both tables. Unicode numbers the octants 1..8 and the sextants 1..6 in that
# same order, so BLOCK OCTANT-247 is the pattern with bits 1, 3 and 6 set and
# BLOCK SEXTANT-235 the one with bits 1, 2 and 4. Index a table by the pattern.
#
# Both tables are literal because the obvious construction is wrong in both
# cases: some patterns were already encoded elsewhere, under descriptive names,
# and were not re-encoded when the set was specified. Octants: 230 characters
# at U+1CD00-U+1CDE5 for 256 patterns, 26 inherited. Sextants: 60 at
# U+1FB00-U+1FB3B for 64 patterns, 4 inherited -- SPACE, LEFT HALF BLOCK, RIGHT
# HALF BLOCK and FULL BLOCK. Offset arithmetic with the wrong exclusion set
# produces plausible, wrong glyphs, and past U+1CDE5 it walks into pictograms:
# an early draft rendered U+1CDED BOTTOM HALF LEFT-FACING RUNNER FRAME-1 into
# the middle of a mark.
#
# The inherited characters come from a far older design pass, and fonts
# commonly do not harmonise them with the ones drawn later -- differing weight
# and coverage show as visible seams within a single rendered mark. Do not
# substitute lookalikes: for most of these patterns there is no alternative
# encoding at all.
# ---------------------------------------------------------------------------

OCTANTS = (
    " 𜺨𜺫🮂𜴀▘𜴁𜴂𜴃𜴄▝𜴅𜴆𜴇𜴈▀𜴉𜴊𜴋𜴌🯦𜴍𜴎𜴏𜴐𜴑𜴒𜴓𜴔𜴕𜴖𜴗"   #   0- 31
    "𜴘𜴙𜴚𜴛𜴜𜴝𜴞𜴟🯧𜴠𜴡𜴢𜴣𜴤𜴥𜴦𜴧𜴨𜴩𜴪𜴫𜴬𜴭𜴮𜴯𜴰𜴱𜴲𜴳𜴴𜴵🮅"   #  32- 63
    "𜺣𜴶𜴷𜴸𜴹𜴺𜴻𜴼𜴽𜴾𜴿𜵀𜵁𜵂𜵃𜵄▖𜵅𜵆𜵇𜵈▌𜵉𜵊𜵋𜵌▞𜵍𜵎𜵏𜵐▛"   #  64- 95
    "𜵑𜵒𜵓𜵔𜵕𜵖𜵗𜵘𜵙𜵚𜵛𜵜𜵝𜵞𜵟𜵠𜵡𜵢𜵣𜵤𜵥𜵦𜵧𜵨𜵩𜵪𜵫𜵬𜵭𜵮𜵯𜵰"   #  96-127
    "𜺠𜵱𜵲𜵳𜵴𜵵𜵶𜵷𜵸𜵹𜵺𜵻𜵼𜵽𜵾𜵿𜶀𜶁𜶂𜶃𜶄𜶅𜶆𜶇𜶈𜶉𜶊𜶋𜶌𜶍𜶎𜶏"   # 128-159
    "▗𜶐𜶑𜶒𜶓▚𜶔𜶕𜶖𜶗▐𜶘𜶙𜶚𜶛▜𜶜𜶝𜶞𜶟𜶠𜶡𜶢𜶣𜶤𜶥𜶦𜶧𜶨𜶩𜶪𜶫"   # 160-191
    "▂𜶬𜶭𜶮𜶯𜶰𜶱𜶲𜶳𜶴𜶵𜶶𜶷𜶸𜶹𜶺𜶻𜶼𜶽𜶾𜶿𜷀𜷁𜷂𜷃𜷄𜷅𜷆𜷇𜷈𜷉𜷊"   # 192-223
    "𜷋𜷌𜷍𜷎𜷏𜷐𜷑𜷒𜷓𜷔𜷕𜷖𜷗𜷘𜷙𜷚▄𜷛𜷜𜷝𜷞▙𜷟𜷠𜷡𜷢▟𜷣▆𜷤𜷥█"   # 224-255
)

SEXTANTS = (
    " 🬀🬁🬂🬃🬄🬅🬆🬇🬈🬉🬊🬋🬌🬍🬎🬏🬐🬑🬒🬓▌🬔🬕🬖🬗🬘🬙🬚🬛🬜🬝"   #   0- 31
    "🬞🬟🬠🬡🬢🬣🬤🬥🬦🬧▐🬨🬩🬪🬫🬬🬭🬮🬯🬰🬱🬲🬳🬴🬵🬶🬷🬸🬹🬺🬻█"   #  32- 63
)

GRID_SIZE = 5

# Each lattice as (table, sub-rows per character, what a blank cell emits,
# sub-rows of blank above the grid).
#
# **The blank differs because the widths do.** Entry 0 of either table is
# U+0020, which is genuinely the character for the empty pattern, but it is
# single-width. Sextants render one column, so one space keeps the column
# count; every octant but that one renders two, so a blank mid-line needs two
# spaces or the line falls a column short and the mark skews against the line
# below. The tables stay canonical; the compensation lives here, at emission.
#
# **The padding goes above in both.** Two lines of octants are eight sub-rows
# against the grid's five and two lines of sextants are six, so there are three
# spare and one. All of them go above, which fills the lower line completely
# with grid and is what lets the tricolour sit flush against it. For octants
# the upper line then holds only the grid's top row, and is entirely blank
# whenever that row is, roughly one repository in eight -- keep both lines
# intact anyway, because anything that strips trailing whitespace collapses the
# mark's height. Centring instead puts a partly-empty line under the tricolour.
OCTANT_LATTICE = (OCTANTS, 4, "  ", 3)
SEXTANT_LATTICE = (SEXTANTS, 3, " ", 1)


def parse_grid(text):
    """A 5x5 grid from 25 characters, or from five rows separated by commas.

    Filled cells are `#`, `1`, `X` or `x`; anything else is empty.
    """
    rows = text.split(",") if "," in text else [
        text[i:i + GRID_SIZE] for i in range(0, len(text), GRID_SIZE)]
    if len(rows) != GRID_SIZE or any(len(r) != GRID_SIZE for r in rows):
        raise ValueError(f"not a {GRID_SIZE}x{GRID_SIZE} grid: {text!r}")
    return [[c in "#1Xx" for c in row] for row in rows]


def lattice_lines(grid, lattice):
    """The grid drawn on one lattice: three characters per line, two lines.

    One routine for both, because the bit order, the cell width and the
    placement of the padding are the same rule in each -- only the numbers
    differ, and those come in on `lattice`.
    """
    table, sub_rows, blank, top_pad = lattice
    cells_per_line = (GRID_SIZE + 1) // 2
    line_count = (GRID_SIZE + top_pad + sub_rows - 1) // sub_rows

    def filled(row, col):
        # The lower bound is not redundant -- top_pad makes `row` negative in
        # the padding, and a negative index would wrap to the grid's bottom.
        return (0 <= row < GRID_SIZE and 0 <= col < GRID_SIZE
                and bool(grid[row][col]))

    lines = []
    for line_index in range(line_count):
        chars = []
        for cell in range(cells_per_line):
            pattern = 0
            for bit in range(sub_rows * 2):
                if filled(line_index * sub_rows + bit // 2 - top_pad,
                          cell * 2 + bit % 2):
                    pattern |= 1 << bit
            chars.append(blank if pattern == 0 else table[pattern])
        lines.append("".join(chars))
    return lines


def octant(grid):
    """The grid on the 2x4 lattice, two lines.

    The contents of `.identicon/repository-identicon.octant`, one line each.
    """
    return lattice_lines(grid, OCTANT_LATTICE)


def sextant(grid):
    """The grid on the 2x3 lattice, two lines.

    The contents of `.identicon/repository-identicon.sextant`, one line each.
    """
    return lattice_lines(grid, SEXTANT_LATTICE)


# ---------------------------------------------------------------------------
# The palette
#
# Unicode names each square by a colour word, and that word is the definition.
# Red, green and blue take the RGB primaries. Orange, purple and brown have no
# primary reading and take their CSS named-colour values.
#
# The name is the anchor, never the installed font: LARGE BLUE SQUARE is
# `#0000FF` whatever a font paints it (the Noto here paints Material Blue 700
# `#1976D2`, and Apple, Twemoji and Windows differ again). A repository must
# produce the same triple for everyone who works on it, so do not sample fonts
# here, and be suspicious of any change that makes the output depend on the
# environment.
#
# Mixtures are averaged in linear light, which is what optical mixing does, and
# compared in Oklab; fixed-lightness HSL, which the identicon's colour comes
# from, clusters badly in the greens.
# ---------------------------------------------------------------------------

PALETTE = (
    ("\U0001F7E5", "red",    0x1F7E5, (0xFF, 0x00, 0x00)),
    ("\U0001F7E7", "orange", 0x1F7E7, (0xFF, 0xA5, 0x00)),
    ("\U0001F7E8", "yellow", 0x1F7E8, (0xFF, 0xFF, 0x00)),
    ("\U0001F7E9", "green",  0x1F7E9, (0x00, 0xFF, 0x00)),
    ("\U0001F7E6", "blue",   0x1F7E6, (0x00, 0x00, 0xFF)),
    ("\U0001F7EA", "purple", 0x1F7EA, (0x80, 0x00, 0x80)),
    ("\U0001F7EB", "brown",  0x1F7EB, (0xA5, 0x2A, 0x2A)),
    ("⬛",     "black",  0x02B1B, (0x00, 0x00, 0x00)),
    ("⬜",     "white",  0x02B1C, (0xFF, 0xFF, 0xFF)),
)


def _linear(component):
    """One sRGB component, 0-255, to linear light."""
    c = component / 255.0
    return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4


def _encode(value):
    """Linear light back to one sRGB component, 0-255."""
    v = min(1.0, max(0.0, value))
    v = 12.92 * v if v <= 0.0031308 else 1.055 * v ** (1 / 2.4) - 0.055
    return int(v * 255 + 0.5)


def _oklab(linear_rgb):
    """Linear-light sRGB to Oklab. Bjorn Ottosson's matrices, unmodified."""
    r, g, b = linear_rgb
    long_ = 0.4122214708 * r + 0.5363325363 * g + 0.0514459929 * b
    med   = 0.2119034982 * r + 0.6806995451 * g + 0.1073969566 * b
    short = 0.0883024619 * r + 0.2817188376 * g + 0.6299787005 * b
    long_, med, short = (math.copysign(abs(v) ** (1 / 3), v)
                         for v in (long_, med, short))
    return (0.2104542553 * long_ + 0.7936177850 * med - 0.0040720468 * short,
            1.9779984951 * long_ - 2.4285922050 * med + 0.4505937099 * short,
            0.0259040371 * long_ + 0.7827717662 * med - 0.8086757660 * short)


_PALETTE_LINEAR = tuple(tuple(_linear(v) for v in rgb) for _, _, _, rgb in PALETTE)
_PALETTE_LAB = tuple(_oklab(lin) for lin in _PALETTE_LINEAR)


def _mix(indices):
    """Linear-light mean of the given palette entries."""
    return tuple(sum(_PALETTE_LINEAR[i][k] for i in indices) / len(indices)
                 for k in range(3))


def parse_hex(value):
    """`#rrggbb` or `rrggbb` to an (r, g, b) triple of 0-255 ints."""
    text = value.strip().lstrip("#")
    if len(text) != 6:
        raise ValueError(f"not a six-digit hex colour: {value!r}")
    return tuple(int(text[i:i + 2], 16) for i in (0, 2, 4))


def nearest_square(rgb):
    """Index into PALETTE of the single square closest to `rgb`.

    Ties break towards the lower index, so the choice is fixed rather than
    left to whatever `min` happens to do.
    """
    target = _oklab(tuple(_linear(v) for v in rgb))
    return min(range(len(PALETTE)),
               key=lambda i: (math.dist(_PALETTE_LAB[i], target), i))


def chosen_indices(rgb):
    """The three PALETTE indices for `rgb`, ascending.

    The nearest single square twice, plus whichever third square brings the
    linear-light mean closest to the target. When the target *is* a palette
    colour the third is the base again, so canonical colours land on three of
    a kind without that being written down anywhere.

    The nearest square is used twice deliberately. Choosing freely from all 165
    mixtures -- every multiset of three drawn from nine squares, C(11,3) --
    minimises error but reads badly, because the eye reads the majority rather
    than averaging: yellow-green `#d5d926` is closest to RED YELLOW GREEN, a
    muddle, where constraining it to YELLOW YELLOW BLACK costs 0.02 mean dE
    across the hue circle and is obviously yellow.
    """
    target = _oklab(tuple(_linear(v) for v in rgb))
    base = nearest_square(rgb)
    best, best_odd = None, None
    for odd in range(len(PALETTE)):
        distance = math.dist(_oklab(_mix((base, base, odd))), target)
        if best is None or distance < best:
            best, best_odd = distance, odd
    return tuple(sorted((base, base, best_odd)))


# ---------------------------------------------------------------------------
# Arrangement
#
# Which squares is a function of the colour; what order is a function of the
# grid. Two inputs, and they must stay two.
# ---------------------------------------------------------------------------

def grid_bits(grid):
    """The fifteen bits of the digest the grid carries, as one number.

    Columns 3 and 4 are the mirror of 1 and 0 and hold nothing, so only the
    left three of each row are read, row by row, left to right.
    """
    value = 0
    for row in grid:
        for cell in row[:3]:
            value = value * 2 + (1 if cell else 0)
    return value


def arrange(indices, grid):
    """Order the chosen squares, deterministically, from the grid.

    `triple_indices` picks *which* squares; this picks the order they are laid
    out in, and the two carry different information.

    **Why order at all.** Which squares to use is a question about fidelity, and
    fidelity is what limits spread: neighbouring colours must choose the same
    squares, or the choice would not be tracking the colour. Measured over the
    whole 1074-colour gamut that leaves about 17 distinguishable triples, and
    the arithmetic is unforgiving -- eight projects collide 85% of the time.
    Choosing squares more cleverly cannot help. Selecting freely from all 165
    combinations rather than constraining to a majority *improves* mean error
    to 0.0393 from 0.0597 and yet leaves spread slightly worse, at 16.5
    effective against 17.5, because both are answering the same question about
    the same one-dimensional gamut.

    Order answers a different question, and costs nothing to the first. The same
    three squares in a different arrangement are the same colours, mixing to the
    same result, named by the same Unicode names: no arrangement renders the
    colour worse than another. So it is free to carry identity, and it roughly
    triples the spread -- 67 distinct arrangements, 49.8 effective.

    **Take the order from the grid, never from the colour.** Hashing an output
    of the mapping cannot add anything the mapping has not already said: over
    four thousand projects it produced fewer distinct marks than there were
    distinct colours. The grid is fifteen bits of the key's digest, drawn from
    a slice disjoint from the one the hue comes from, and `text()` is already
    holding it.

    What is given up is that a consumer holding only `.colour` can compute the
    mark -- already only mostly true, since recovering the wheel position from a
    quantised colour puts about one project in forty in the wrong arc. Adjacent
    colours have unrelated grids, so they get unrelated arrangements; the
    mapping is still not monotonic in hue, and a triple does not say where on
    the wheel a colour sits.
    """
    options = sorted(set(itertools.permutations(indices)))
    return options[grid_bits(grid) % len(options)]


def hex_colour(rgb):
    """`#rrggbb`. Public surface -- the vendoring consumers and
    `work-in-progress/` call it."""
    return "#{:02x}{:02x}{:02x}".format(*rgb)


def tricolour_indices(rgb, grid):
    """The three PALETTE indices for `rgb`, in the order they are laid out.

    Takes the grid as well as the colour, because the order comes from the
    grid -- see `arrange`.
    """
    return arrange(chosen_indices(rgb), grid)


def tricolour(rgb, grid):
    """The three emoji for `rgb`, as one string of three characters.

    The contents of `.identicon/repository-identicon.tricolour`.
    """
    return "".join(PALETTE[i][0] for i in tricolour_indices(rgb, grid))


def tricolour_names(rgb, grid):
    """The three colour names for `rgb`, in laid-out order.

    Public surface. Nothing in this repository calls it; the consumers that
    vendor this module do, to log or explain a mark.
    """
    return tuple(PALETTE[i][1] for i in tricolour_indices(rgb, grid))


def tricolour_detail(rgb, grid):
    """Everything about the choice, for tests and for explaining a result.

    `indices` is the multiset the fidelity search chose; `arranged` is the order
    it is laid out in. Both are reported because they answer different
    questions, and a result that looks wrong is usually wrong in only one.
    """
    indices = chosen_indices(rgb)
    arranged = arrange(indices, grid)
    mix = _mix(indices)
    target = _oklab(tuple(_linear(v) for v in rgb))
    return {
        "indices": indices,
        "arranged": arranged,
        "emoji": "".join(PALETTE[i][0] for i in arranged),
        "names": tuple(PALETTE[i][1] for i in arranged),
        "base": PALETTE[nearest_square(rgb)][1],
        "mix_hex": hex_colour(tuple(_encode(v) for v in mix)),
        "delta_e": math.dist(_oklab(mix), target),
    }


# ---------------------------------------------------------------------------
# The whole mark
# ---------------------------------------------------------------------------

def text(grid, rgb, lattice=SEXTANT_LATTICE):
    """A lattice and the tricolour composed: two lines, the tricolour ending
    the lower one.

    Takes the 5x5 matrix and the colour, and nothing else. This is the whole of
    what `.txt` holds beyond `.sextant` and `.tricolour` -- one space between
    them, and which line they share.

    **Sextants by default**, because the default has to work on the host that
    has fewer glyphs, and the octant set is four years younger. A caller that
    knows its host can pass `OCTANT_LATTICE`; `.octant` is written from it so
    that a consumer needs no argument either.
    """
    lines = lattice_lines(grid, lattice)
    lines[-1] = f"{lines[-1]} {tricolour(rgb, grid)}"
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Self-check and demo
# ---------------------------------------------------------------------------

def selftest():
    """Invariants that hold for any palette and any Unicode host."""
    import unicodedata
    host = tuple(int(p) for p in unicodedata.unidata_version.split(".")[:1])

    for table, size, prefix, drawn, since in (
            (OCTANTS, 256, "BLOCK OCTANT-", 230, (16,)),
            (SEXTANTS, 64, "BLOCK SEXTANT-", 60, (13,))):
        assert len(table) == size, (prefix, len(table))
        assert len(set(table)) == size, f"{prefix} table has duplicates"
        # Re-derive the table from the Unicode database where the host has it,
        # so the literal above is verified rather than trusted.
        if host < since:
            continue
        named = 0
        for pattern, char in enumerate(table):
            try:
                name = unicodedata.name(char)
            except ValueError:
                continue
            if not name.startswith(prefix):
                continue
            named += 1
            bits = 0
            for digit in name[len(prefix):]:
                bits |= 1 << (int(digit) - 1)
            assert bits == pattern, (name, pattern, bits)
        assert named == drawn, f"expected {drawn} {prefix} characters, saw {named}"

    # The sextant patterns encoded elsewhere, by name rather than by codepoint.
    if host >= (13,):
        for pattern, name in ((0, "SPACE"), (0b010101, "LEFT HALF BLOCK"),
                              (0b101010, "RIGHT HALF BLOCK"),
                              (0b111111, "FULL BLOCK")):
            assert unicodedata.name(SEXTANTS[pattern]) == name, pattern

    # Every canonical colour is three of its own square, with no special case.
    # Three of a kind has one arrangement, so the grid cannot change it.
    sample_grid = parse_grid(".#.#.,.#.#.,#...#,#.#.#,.#.#.")
    for index, (char, name, _, rgb) in enumerate(PALETTE):
        detail = tricolour_detail(rgb, sample_grid)
        assert detail["indices"] == (index, index, index), (name, detail)
        assert detail["delta_e"] == 0.0, (name, detail["delta_e"])
        assert detail["emoji"] == char * 3, (name, detail["emoji"])

    # The majority constraint: some colour always appears at least twice.
    for value in range(0, 0x1000000, 0x3F1D7):
        indices = chosen_indices(((value >> 16) & 0xFF,
                                  (value >> 8) & 0xFF, value & 0xFF))
        assert len(set(indices)) <= 2, indices

    # Arranging reorders and never substitutes: the multiset is what carries
    # the colour, so arrangement must not be able to change it.
    for value in range(0, 0x1000000, 0x3F1D7):
        rgb = ((value >> 16) & 0xFF, (value >> 8) & 0xFF, value & 0xFF)
        indices = chosen_indices(rgb)
        arranged = arrange(indices, sample_grid)
        assert sorted(arranged) == sorted(indices), (rgb, indices, arranged)
        assert arrange(indices, sample_grid) == arranged, "not deterministic"

    # The squares come from the colour alone, and the two sample grids differ.
    other = parse_grid("#####,.....,#####,.....,#####")
    assert (chosen_indices((0x26, 0x92, 0xD9))
            == chosen_indices(parse_hex("#2692d9")))
    assert (tricolour(parse_hex("#2692d9"), sample_grid)
            == tricolour((0x26, 0x92, 0xD9), sample_grid))
    assert grid_bits(sample_grid) != grid_bits(other), "premise changed"

    # Two projects landing on the same colour must not land on the same mark:
    # hashing the order from the colour forced a shared arrangement.
    shared = parse_hex("#2692d9")
    marks = {tricolour(shared, g) for g in (sample_grid, other)}
    assert len(marks) == 2, (
        "same colour, different patterns, still one mark: the arrangement is "
        "not carrying identity")

    # The pair that motivated arranging at all: three units apart in one
    # channel, identical multiset, and they must not render alike. They have
    # unrelated grids in practice, which is what separates them now.
    near_a, near_b = parse_hex("#2692d9"), parse_hex("#2695d9")
    assert chosen_indices(near_a) == chosen_indices(near_b), "premise changed"
    assert (tricolour(near_a, sample_grid)
            != tricolour(near_b, other)), (
        "adjacent colours collapsed to one tricolour again")

    # One mark pinned whole on each lattice, so a change to a table, a padding
    # or the arrangement has to be written down here before it can ship. The
    # squares are green, blue, blue by fidelity; the order comes from the grid,
    # so both lattices carry the same tricolour.
    grid = parse_grid(".#.#.,.#.#.,#...#,#.#.#,.#.#.")
    for lattice, expected in (
            (SEXTANT_LATTICE, "\U0001FB26\U0001FB26 \n"
                              "\U0001FB23\U0001FB22\U0001FB04 "
                              "\U0001F7E6\U0001F7E9\U0001F7E6"),
            (OCTANT_LATTICE, "\U0001CEA0\U0001CEA0  \n"
                             "\U0001CD86\U0001CD82\U0001FBE6 "
                             "\U0001F7E6\U0001F7E9\U0001F7E6")):
        actual = text(grid, parse_hex("#2692d9"), lattice)
        assert actual == expected, actual

    # Both lattices are lossless, which is the whole reason there is a choice
    # to make: neither loses a cell the other keeps.
    for shape in ("#" * 25, "." * 25, ".#.#.,#...#,.....,#...#,.#.#.",
                  "#...#,.###.,#.#.#,.....,##.##"):
        source = parse_grid(shape)
        for lattice in (OCTANT_LATTICE, SEXTANT_LATTICE):
            assert _recover(lattice_lines(source, lattice), lattice) == source, (
                shape, lattice[1])

    # The tricolour terminates the mark: it is on the last line, not the first.
    full = parse_grid("#" * 25)
    mark = text(full, parse_hex("#2692d9"))
    first, last = mark.split("\n")
    assert not any(p[0] in first for p in PALETTE), first
    assert last.endswith(tricolour(parse_hex("#2692d9"), full)), last

    # Whatever the padding or the pattern, either lattice is two lines of three
    # cells, and every line is the same number of columns wide -- which is the
    # property the blank exists to preserve. Blanks are one character wide for
    # sextants and two for octants, so a cell count needs the blank width.
    for shape in ("#" * 25, "." * 25, ".#.#.,#...#,.....,#...#,.#.#."):
        for lattice in (OCTANT_LATTICE, SEXTANT_LATTICE):
            blank = lattice[2]
            rendered = lattice_lines(parse_grid(shape), lattice)
            assert len(rendered) == 2, rendered
            for line in rendered:
                assert line.count(" ") % len(blank) == 0, repr(line)
                cells = (sum(1 for c in line if c != " ")
                         + line.count(" ") // len(blank))
                assert cells == 3, (repr(line), cells)
    return True


def _recover(lines, lattice):
    """The grid read back out of its rendered lines. For `selftest` only."""
    table, sub_rows, blank, top_pad = lattice
    index = {char: pattern for pattern, char in enumerate(table)}
    grid = [[False] * GRID_SIZE for _ in range(GRID_SIZE)]
    for line_index, line in enumerate(lines):
        cells = []
        while line:
            if line.startswith(blank):
                cells.append(0)
                line = line[len(blank):]
            else:
                cells.append(index[line[0]])
                line = line[1:]
        for cell, pattern in enumerate(cells):
            for bit in range(sub_rows * 2):
                if not pattern & (1 << bit):
                    continue
                row = line_index * sub_rows + bit // 2 - top_pad
                col = cell * 2 + bit % 2
                assert 0 <= row < GRID_SIZE and 0 <= col < GRID_SIZE, (row, col)
                grid[row][col] = True
    return grid


def _main(argv):
    if not argv or argv[0] in ("-h", "--help"):
        print(__doc__.strip().splitlines()[0])
        print("\nusage: text-identicon.py --selftest")
        print("       text-identicon.py [--octant] <#rrggbb> <grid>")
        print("\n  <grid>     25 characters, or five rows separated by commas;")
        print("             `#`, `1`, `X` or `x` is a filled cell.")
        print("  --octant   draw on the 2x4 lattice; the default is 2x3.")
        return 0
    lattice = SEXTANT_LATTICE
    if argv and argv[0] == "--octant":
        lattice, argv = OCTANT_LATTICE, argv[1:]
    if argv and argv[0] == "--selftest":
        selftest()
        print("selftest: ok")
        return 0
    if len(argv) != 2:
        print("need a colour and a grid; --help for the spelling")
        return 2
    print(text(parse_grid(argv[1]), parse_hex(argv[0]), lattice))
    return 0


if __name__ == "__main__":
    import sys
    raise SystemExit(_main(sys.argv[1:]))
