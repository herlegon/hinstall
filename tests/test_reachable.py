from pathlib import Path
import signal
import sys
sys.path.append(str(Path(__file__).resolve().parent.parent))

from hinstall import (
    get_domain_from_url,
    check_site_reachable,
    ilog
)

if __name__ == "__main__":
    signal.signal(signal.SIGINT, signal.SIG_DFL)
    ilog.setLevel("DEBUG")

    urls = [
        "https://www.github.com",
        "https://github.com/herlegon/rehost/releases/download/external",
    ]
    for url in urls:
        domain = get_domain_from_url(url)
        reachable = check_site_reachable(url=domain)
        if not reachable:
            ilog.error(f"{domain} is not reachable")
        else:
            ilog.info(f"{domain} is alive")
