from app.worker.main import parse_args


def test_parse_args_accepts_worker_id_and_display() -> None:
    args = parse_args(["--worker-id", "worker-2", "--display", ":22", "--once"])

    assert args.worker_id == "worker-2"
    assert args.display == ":22"
    assert args.once is True
