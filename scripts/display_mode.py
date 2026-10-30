"""Preserve the TV's preferred mode; 720p is an explicit opt-in."""

import argparse
import json
import subprocess


def choose_mode(outputs):
    for output in outputs:
        if not isinstance(output, dict) or not output.get("enabled"):
            continue
        name = output.get("name", "")
        if not name.startswith("HDMI"):
            continue
        modes = [
            mode
            for mode in output.get("modes", [])
            if mode.get("width") == 1280
            and mode.get("height") == 720
            and 49 <= float(mode.get("refresh", 0)) <= 61
        ]
        if modes:
            mode = min(modes, key=lambda m: abs(float(m["refresh"]) - 60))
            return name, f"1280x720@{float(mode['refresh']):.6f}Hz"
    return None


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--prefer-720p", action="store_true", help="Opt in to an advertised 720p mode"
    )
    args = parser.parse_args(argv)
    if not args.prefer_720p:
        # Sharp HDMI dropped/reconnected twice after our startup 720p modeset.
        # Let Cage keep the EDID preferred mode instead of renegotiating it.
        print(
            "Keeping the TV preferred HDMI mode; no startup resolution change.",
            flush=True,
        )
        return
    try:
        result = subprocess.run(
            ["/usr/bin/wlr-randr", "--json"],
            capture_output=True,
            text=True,
            timeout=5,
            check=True,
        )
        selected = choose_mode(json.loads(result.stdout))
        if selected:
            subprocess.run(
                ["/usr/bin/wlr-randr", "--output", selected[0], "--mode", selected[1]],
                timeout=5,
                check=True,
            )
            print("HDMI low-memory mode:", *selected, flush=True)
        else:
            print(
                "Keeping native display mode: no advertised HDMI 720p mode.", flush=True
            )
    except (
        OSError,
        ValueError,
        TypeError,
        KeyError,
        subprocess.SubprocessError,
    ) as error:
        print("Keeping native display mode:", error, flush=True)


if __name__ == "__main__":
    main()
