import re
import subprocess
from pathlib import Path


# ============================================================
# CONFIG
# ============================================================

OCR_FILE = Path("./ocr.txt")
OUTPUT_FILE = Path("./llm_context.txt")

# Number of lines around a matched field to include.
SNIPPET_CONTEXT = 2

# Maximum snippets per field.
MAX_MATCHES_PER_FIELD = 3


# ============================================================
# FIELDS TO EXTRACT
# ============================================================
#
# The LLM will ONLY receive evidence for these fields.
#
# Add/change fields here according to your insurance schema.
#

FIELDS = {
    "address": [
        r"address\s*:",
        r"property\s+address\s*:",
    ],

    "building_type": [
        r"building\s+type\s*:",
        r"property\s+type\s*:",
    ],


    "damage_description": [
        r"damage\s+description\s*:",
        r"description\s+of\s+damage\s*:",
    ],




}


# ============================================================
# RUN RG
# ============================================================

def run_rg(pattern, start_line=None, end_line=None):
    """
    Run ripgrep against OCR file.

    start_line/end_line are used to restrict the search to
    a particular Location + Building section.
    """

    cmd = [
        "rg",
        "-i",
        "-n",
        "--no-heading",
        "--color", "never",
    ]

    if start_line is not None:
        cmd.extend([
            "-A",
            str(end_line - start_line),
        ])

    cmd.extend([
        pattern,
        str(OCR_FILE),
    ])

    result = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        timeout=10,
    )

    if result.returncode == 1:
        return []

    if result.returncode != 0:
        raise RuntimeError(
            f"rg failed:\n{result.stderr}"
        )

    return result.stdout.splitlines()


# ============================================================
# LOAD OCR
# ============================================================

def load_ocr():
    if not OCR_FILE.exists():
        raise FileNotFoundError(
            f"OCR file not found: {OCR_FILE.resolve()}"
        )

    return OCR_FILE.read_text(
        encoding="utf-8"
    )


# ============================================================
# FIND STRUCTURAL MARKERS
# ============================================================

def find_markers():
    """
    Find ONLY exact structural lines:

        LOCATION 1
        BUILDING 1
        BUILDING 2

    It intentionally does NOT match:

        Building 1 additional notes:
        Location 1 address:
        Location 1 damage summary:

    Optional OCR line numbering is supported:

        14:BUILDING 1
        50:LOCATION 2
    """

    pattern = (
        r"^\s*"
        r"(?:\d+\s*[:.-]\s*)?"
        r"(LOCATION\s+\d+|BUILDING\s+\d+)"
        r"\s*$"
    )

    result = subprocess.run(
        [
            "rg",
            "-i",
            "-n",
            "--no-heading",
            "--color", "never",
            pattern,
            str(OCR_FILE),
        ],
        capture_output=True,
        text=True,
        timeout=10,
    )

    if result.returncode == 1:
        return []

    if result.returncode != 0:
        raise RuntimeError(result.stderr)

    markers = []

    for raw_line in result.stdout.splitlines():

        # Example:
        #
        # 1:LOCATION 1
        # 5:BUILDING 1
        #
        line_number, text = raw_line.split(":", 1)

        text = text.strip()

        # Remove OCR numbering from text if it exists.
        text = re.sub(
            r"^\d+\s*[:.-]\s*",
            "",
            text,
        )

        markers.append(
            {
                "line": int(line_number),
                "text": text.strip(),
            }
        )

    return markers


# ============================================================
# BUILD LOCATION / BUILDING HIERARCHY
# ============================================================

def detect_structure(markers):

    location_pattern = re.compile(
        r"^LOCATION\s+(\d+)$",
        re.IGNORECASE,
    )

    building_pattern = re.compile(
        r"^BUILDING\s+(\d+)$",
        re.IGNORECASE,
    )

    locations = []

    current_location = None

    for marker in markers:

        text = marker["text"]

        location_match = location_pattern.match(text)

        if location_match:

            location_number = int(
                location_match.group(1)
            )

            current_location = {
                "number": location_number,
                "start": marker["line"],
                "buildings": [],
            }

            locations.append(
                current_location
            )

            continue

        building_match = building_pattern.match(text)

        if building_match and current_location:

            building_number = int(
                building_match.group(1)
            )

            current_location["buildings"].append(
                {
                    "number": building_number,
                    "start": marker["line"],
                }
            )

    return locations


# ============================================================
# CALCULATE BUILDING BOUNDARIES
# ============================================================

def calculate_boundaries(locations, total_lines):

    """
    Converts:

        LOCATION 1
            BUILDING 1
            BUILDING 2
            BUILDING 3

        LOCATION 2
            BUILDING 1
            BUILDING 2
            BUILDING 3

    into:

        Location 1 / Building 1
            start = X
            end   = Y

        Location 1 / Building 2
            start = Y
            end   = Z
    """

    for location_index, location in enumerate(locations):

        buildings = location["buildings"]

        for building_index, building in enumerate(buildings):

            start = building["start"]

            # Next building in same location.
            if building_index + 1 < len(buildings):

                end = (
                    buildings[
                        building_index + 1
                    ]["start"] - 1
                )

            # Last building in location.
            else:

                # Next location.
                if location_index + 1 < len(locations):

                    end = (
                        locations[
                            location_index + 1
                        ]["start"] - 1
                    )

                else:

                    end = total_lines

            building["end"] = end

    return locations


# ============================================================
# SEARCH FIELD INSIDE BUILDING
# ============================================================

def search_field(
    lines,
    field_patterns,
    start_line,
    end_line,
):
    """
    Search for a field only inside the exact
    Location + Building boundary.

    Returns small snippets rather than the entire section.
    """

    matches = []

    # Convert to zero-based Python indexes.
    start_index = start_line - 1
    end_index = end_line

    section_lines = lines[
        start_index:end_index
    ]

    for relative_index, line in enumerate(
        section_lines
    ):

        for pattern in field_patterns:

            try:
                matched = re.search(
                    pattern,
                    line,
                    re.IGNORECASE,
                )

            except re.error as exc:
                raise ValueError(
                    f"Invalid regex: {pattern}"
                ) from exc

            if not matched:
                continue

            actual_line_number = (
                start_line
                + relative_index
            )

            # --------------------------------------------
            # Capture small context around matched line
            # --------------------------------------------

            snippet_start = max(
                0,
                relative_index - SNIPPET_CONTEXT,
            )

            snippet_end = min(
                len(section_lines),
                relative_index
                + SNIPPET_CONTEXT
                + 1,
            )

            snippet_lines = section_lines[
                snippet_start:snippet_end
            ]

            cleaned = []

            for snippet_line in snippet_lines:

                snippet_line = snippet_line.strip()

                if snippet_line:
                    cleaned.append(
                        snippet_line
                    )

            snippet = "\n".join(
                cleaned
            )

            matches.append(
                {
                    "line": actual_line_number,
                    "snippet": snippet,
                }
            )

            break

        if len(matches) >= MAX_MATCHES_PER_FIELD:
            break

    return matches


# ============================================================
# BUILD LLM CONTEXT
# ============================================================

def build_llm_context(
    ocr_text,
    locations,
):

    lines = ocr_text.splitlines()

    output = []

    for location in locations:

        location_number = location["number"]

        output.append(
            f"LOCATION {location_number}"
        )

        # ----------------------------------------------------
        # Location-level fields
        # ----------------------------------------------------
        #
        # We can search fields against the location area
        # separately if required.
        #
        # For now, address is considered a location field
        # if it appears before the first building.
        #

        buildings = location["buildings"]

        if not buildings:
            continue

        first_building_start = buildings[0]["start"]

        location_start = location["start"]

        location_end = (
            first_building_start - 1
        )

        output.append(
            "LOCATION EVIDENCE:"
        )

        for field_name in ["address"]:

            patterns = FIELDS.get(
                field_name,
                [],
            )

            matches = search_field(
                lines,
                patterns,
                location_start,
                location_end,
            )

            if not matches:
                continue

            output.append(
                f"[{field_name}]"
            )

            for match in matches:

                output.append(
                    f"Line {match['line']}: "
                    f"{match['snippet']}"
                )

        output.append("")

        # ----------------------------------------------------
        # Buildings
        # ----------------------------------------------------

        for building in buildings:

            building_number = building[
                "number"
            ]

            building_start = building[
                "start"
            ]

            building_end = building[
                "end"
            ]

            output.append(
                f"BUILDING {building_number}"
            )

            output.append(
                "FIELD EVIDENCE:"
            )

            found_any_field = False

            # ----------------------------------------------
            # Search every required field
            # ----------------------------------------------

            for field_name, patterns in FIELDS.items():

                # Address was already searched at location
                # level.
                if field_name == "address":
                    continue

                matches = search_field(
                    lines,
                    patterns,
                    building_start,
                    building_end,
                )

                if not matches:
                    continue

                found_any_field = True

                output.append(
                    f"[{field_name}]"
                )

                for match in matches:

                    output.append(
                        f"Line {match['line']}: "
                        f"{match['snippet']}"
                    )

                output.append("")

            if not found_any_field:

                output.append(
                    "No configured field evidence found."
                )

            output.append("")
            output.append("-" * 60)
            output.append("")

    return "\n".join(output)


# ============================================================
# SAVE
# ============================================================

def save_context(context):

    OUTPUT_FILE.write_text(
        context,
        encoding="utf-8",
    )

    print(
        f"\nLLM context saved to:"
        f"\n{OUTPUT_FILE.resolve()}"
    )


# ============================================================
# PRINT STRUCTURE
# ============================================================

def print_structure(locations):

    print("\n" + "=" * 70)
    print("DOCUMENT STRUCTURE")
    print("=" * 70)

    for location in locations:

        print(
            f"\nLocation {location['number']}"
        )

        for building in location["buildings"]:

            print(
                f"    Building "
                f"{building['number']} "
                f"({building['start']}"
                f"-{building['end']})"
            )


# ============================================================
# MAIN
# ============================================================

def main():

    print("Loading OCR...")

    ocr_text = load_ocr()

    lines = ocr_text.splitlines()

    print(
        f"OCR lines: {len(lines)}"
    )

    # --------------------------------------------------------
    # 1. Find structural markers
    # --------------------------------------------------------

    print(
        "\nFinding Location / Building markers..."
    )

    markers = find_markers()

    if not markers:

        raise RuntimeError(
            "No Location / Building markers found."
        )

    print("\nMarkers:")

    for marker in markers:

        print(
            f"{marker['line']:>4}: "
            f"{marker['text']}"
        )

    # --------------------------------------------------------
    # 2. Build hierarchy
    # --------------------------------------------------------

    locations = detect_structure(
        markers
    )

    # --------------------------------------------------------
    # 3. Calculate exact boundaries
    # --------------------------------------------------------

    locations = calculate_boundaries(
        locations,
        len(lines),
    )

    # --------------------------------------------------------
    # 4. Print hierarchy
    # --------------------------------------------------------

    print_structure(
        locations
    )

    # --------------------------------------------------------
    # 5. Retrieve field evidence
    # --------------------------------------------------------

    print(
        "\n" + "=" * 70
    )

    print(
        "BUILDING FIELD RETRIEVAL"
    )

    print(
        "=" * 70
    )

    llm_context = build_llm_context(
        ocr_text,
        locations,
    )

    # --------------------------------------------------------
    # 6. Print final LLM context
    # --------------------------------------------------------

    print(
        "\n" + "=" * 70
    )

    print(
        "LLM CONTEXT"
    )

    print(
        "=" * 70
    )

    print(llm_context)

    # --------------------------------------------------------
    # 7. Save
    # --------------------------------------------------------

    save_context(
        llm_context
    )


if __name__ == "__main__":
    main()