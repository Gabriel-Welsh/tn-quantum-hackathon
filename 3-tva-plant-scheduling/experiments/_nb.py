"""Load the functions defined in ../notebooks/starter.ipynb (through `def schedule_day`)."""
import contextlib, io, json, os, sys

import matplotlib
matplotlib.use("Agg")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def load_notebook():
    sys.path.insert(0, os.path.join(ROOT, "scheduling"))
    os.chdir(ROOT)
    nb = json.load(open(os.path.join(ROOT, "notebooks", "starter.ipynb")))
    code = []
    for cell in nb["cells"]:
        if cell["cell_type"] != "code":
            continue
        src = "".join(cell["source"])
        src = "\n".join("    pass" if l.strip().startswith("%") else l for l in src.splitlines())
        code.append(src.replace("plt.show()", "plt.close('all')"))
        if "def schedule_day" in src:
            break
    ns = {}
    with contextlib.redirect_stdout(io.StringIO()):
        exec("\n\n".join(code), ns)
    return ns
