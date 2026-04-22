import subprocess
import sys
import time

BROADCAST_SINKS = ["hapax-pc-loudnorm-playback", "hapax-loudnorm-playback"]

PRIVATE_SINKS = ["hapax-private-playback"]

TARGET = (
    "alsa_output.usb-ZOOM_Corporation_L-12_8253FFFFFFFFFFFF9B5FFFFFFFFFFFFF-00.analog-surround-40"
)


def get_links():
    try:
        return subprocess.check_output(["pw-link", "-l"]).decode()
    except Exception:
        return ""


def get_inputs():
    try:
        return subprocess.check_output(["pw-link", "-i"]).decode()
    except Exception:
        return ""


def get_outputs():
    try:
        return subprocess.check_output(["pw-link", "-o"]).decode()
    except Exception:
        return ""


def link(src, dst):
    try:
        subprocess.run(
            ["pw-link", src, dst], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
        )
        print(f"Linked {src} -> {dst}", flush=True)
    except Exception as e:
        print(f"Failed to link {src} -> {dst}: {e}", file=sys.stderr, flush=True)


def main():
    print("USB Router started.", flush=True)
    while True:
        links_output = get_links()
        inputs = get_inputs()
        outputs = get_outputs()

        # Check if the target ALSA sink exists
        if f"{TARGET}:playback_RL" not in inputs:
            time.sleep(2)
            continue

        for sink in BROADCAST_SINKS:
            if f"{sink}:output_FL" in outputs:
                if f"{sink}:output_FL\n  |-> {TARGET}:playback_RL" not in links_output:
                    link(f"{sink}:output_FL", f"{TARGET}:playback_RL")
            if f"{sink}:output_FR" in outputs:
                if f"{sink}:output_FR\n  |-> {TARGET}:playback_RR" not in links_output:
                    link(f"{sink}:output_FR", f"{TARGET}:playback_RR")

        for sink in PRIVATE_SINKS:
            if f"{sink}:output_FL" in outputs:
                if f"{sink}:output_FL\n  |-> {TARGET}:playback_FL" not in links_output:
                    # Unlink from RL/RR if it was previously linked there by the buggy version
                    subprocess.run(
                        ["pw-link", "-d", f"{sink}:output_FL", f"{TARGET}:playback_RL"],
                        stderr=subprocess.DEVNULL,
                    )
                    link(f"{sink}:output_FL", f"{TARGET}:playback_FL")
            if f"{sink}:output_FR" in outputs:
                if f"{sink}:output_FR\n  |-> {TARGET}:playback_FR" not in links_output:
                    subprocess.run(
                        ["pw-link", "-d", f"{sink}:output_FR", f"{TARGET}:playback_RR"],
                        stderr=subprocess.DEVNULL,
                    )
                    link(f"{sink}:output_FR", f"{TARGET}:playback_FR")

        time.sleep(2)


if __name__ == "__main__":
    main()
