"""Demo script: simulates 3 training runs with noisy loss curves and
different configs, so `trackr list` / `trackr ui` have something to show.
"""
import random
import tempfile
import time
from pathlib import Path

import trackr


def train_run(name, lr, epochs, seed):
    random.seed(seed)
    run = trackr.init(
        project="demo",
        name=name,
        config={"lr": lr, "epochs": epochs, "seed": seed},
    )
    loss = 2.0
    for step in range(epochs):
        loss = max(0.02, loss * random.uniform(0.85, 0.97))
        val_acc = min(0.99, 0.4 + 0.55 * (1 - loss / 2.0) + random.uniform(-0.02, 0.02))
        run.log({"loss": loss, "val_acc": val_acc}, step=step)
        time.sleep(0.01)

    with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False) as f:
        f.write(f"run summary for {name}\nfinal_loss={loss:.4f}\n")
        summary_path = Path(f.name)
    run.log_artifact(str(summary_path))
    summary_path.unlink()

    run.finish(status="completed")
    print(f"finished {run.run_id} ({name})")
    return run


def main():
    train_run("cnn-baseline", lr=3e-4, epochs=20, seed=1)
    train_run("cnn-highlr", lr=1e-3, epochs=20, seed=2)
    train_run("cnn-lowlr", lr=1e-5, epochs=20, seed=3)


if __name__ == "__main__":
    main()
