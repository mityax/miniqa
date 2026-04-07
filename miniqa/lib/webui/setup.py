import os.path
import sys
import tempfile
from pathlib import Path

from miniqa.lib.webui.config import STATIC_PATH

# This script fetches the required frontend resources from CDN such that the webui works
# fully offline afterward.

JS_PACKAGE_DOWNLOAD_URLS = [
    {
        "target": "vue",
        "urls": ["https://unpkg.com/vue@3/dist/vue.esm-browser.prod.js"]
    },
    {
        "target": "novnc",
        "urls": ["https://registry.npmjs.org/@novnc/novnc/-/novnc-1.7.0-beta.tgz"],
        "sub_directory": "package/",
    },
    {
        "target": "ace",
        "urls":  [
          "https://cdn.jsdelivr.net/npm/ace-builds@1.43.6/src-min-noconflict/ace.js",
          "https://cdn.jsdelivr.net/npm/ace-builds@1.43.6/src-min-noconflict/mode-yaml.js",
          "https://cdn.jsdelivr.net/npm/ace-builds@1.43.6/src-min-noconflict/theme-tomorrow_night_bright.js",
          "https://cdn.jsdelivr.net/npm/ace-builds@1.43.6/src-min-noconflict/theme-chrome.js",
          "https://cdn.jsdelivr.net/npm/ace-builds@1.43.6/src-min-noconflict/ext-language_tools.js",
        ]
    },
    {
        "target": "feather-icons",
        "urls": ["https://cdn.jsdelivr.net/npm/feather-icons/dist/feather.min.js"]
    },
    {
        "target": "js-yaml",
        "urls": ["https://cdn.jsdelivr.net/npm/js-yaml@4.1.0/dist/js-yaml.min.js"]
    },
]


def setup_dependencies(skip_confirm: bool = False):
    js_vendor_pth = STATIC_PATH / 'vendor'
    js_vendor_pth.mkdir(exist_ok=True)

    required = [pkg for pkg in JS_PACKAGE_DOWNLOAD_URLS if not (js_vendor_pth / pkg["target"]).exists()]

    if not required:
        return

    if not skip_confirm and not os.environ.get("MINIQA_SETUP_SKIP_CONFIRM", "0").lower() in ('1', 'yes', 'true'):
        print(f"These resources need to be downloaded to for the webui to work (this is a one-time setup):")
        print(" - " + "\n - ".join(f"{req['target']} from:\n    - {'\n    - '.join(req['urls'])}" for req in required))
        print("After these files have been downloaded, miniQA works fully offline.")

        if input("Ok? [y/N]: ").lower() not in ('y', 'yes'):
            print("Aborted.")
            sys.exit()

    import io, tarfile, urllib.request

    for package in required:
        pth = js_vendor_pth / package["target"]

        for url in package["urls"]:
            print(f"Downloading {url}...")

            if url.endswith(".tgz"):
                subdir = package.get("sub_directory")

                data = urllib.request.urlopen(url).read()
                with tempfile.TemporaryDirectory() as tmpdir:
                    with tarfile.open(fileobj=io.BytesIO(data), mode="r:gz") as tar:
                        tar.extractall(path=tmpdir, members=[m for m in tar.getmembers() if m.name.startswith(subdir or "")])

                    (Path(tmpdir) / subdir).move(pth)
            else:
                pth.mkdir(exist_ok=True)
                urllib.request.urlretrieve(url, pth / os.path.basename(url))
