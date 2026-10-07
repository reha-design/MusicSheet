import json

import pytest


def arguments(audio, checkpoint, output):
    path, digest = checkpoint
    return ["--input-audio",str(audio),"--checkpoint",str(path),"--checkpoint-sha256",digest,
            "--device","cpu","--output-dir",str(output)]


@pytest.mark.parametrize("args", [[],["--device","cuda"],["--secret-sentinel"],
    ["--input-audio","secret-sentinel"]])
def test_invalid_cli_args_are_generic(args,capsys):
    from musicsheet_piano_amt_worker.cli import main
    assert main(args) == 2
    captured = capsys.readouterr()
    assert "secret-sentinel" not in captured.out+captured.err and "Traceback" not in captured.err


def test_valid_cli_fake_backend_and_output_failure(audio,checkpoint,prediction,tmp_path,monkeypatch,capsys):
    from musicsheet_piano_amt_worker import cli
    calls=[]
    def fake(*args, **kwargs):
        calls.append(kwargs)
        return prediction
    monkeypatch.setattr(cli,"run_prediction",fake)
    args = arguments(audio(),checkpoint,tmp_path/"result")
    assert cli.main(args) == 0 and len(calls) == 1
    result=json.loads((tmp_path/"result"/"raw_transcription.json").read_text())
    assert result["device"] == "cpu" and result["model"] == "Note_pedal"
    assert cli.main(args) == 4
    assert "Traceback" not in capsys.readouterr().err


def test_setup_refuses_model_call_on_bad_checkpoint(audio,checkpoint,tmp_path,monkeypatch):
    from musicsheet_piano_amt_worker import cli
    args = arguments(audio(),checkpoint,tmp_path/"result")
    args[5] = "secret-sentinel"
    monkeypatch.setattr(cli,"run_prediction",lambda *a,**k: pytest.fail("Bad checkpoint reached model"))
    assert cli.main(args) == 2 and not (tmp_path/"result").exists()


def test_inference_exception_is_generic(audio,checkpoint,tmp_path,monkeypatch,capsys):
    from musicsheet_piano_amt_worker import cli
    def fail(*args,**kwargs):
        raise RuntimeError("secret-sentinel")
    monkeypatch.setattr(cli,"run_prediction",fail)
    assert cli.main(arguments(audio(),checkpoint,tmp_path/"result")) == 3
    assert "secret-sentinel" not in str(capsys.readouterr()) and not (tmp_path/"result").exists()


def test_invalid_raw_prediction_is_output_exit4(audio,checkpoint,tmp_path,monkeypatch,capsys):
    from musicsheet_piano_amt_worker import cli
    from musicsheet_piano_amt_worker.output import OutputValidationError
    def invalid(*args,**kwargs): raise OutputValidationError("secret-sentinel")
    monkeypatch.setattr(cli,"run_prediction",invalid)
    assert cli.main(arguments(audio(),checkpoint,tmp_path/"result")) == 4
    assert "secret-sentinel" not in str(capsys.readouterr()) and not (tmp_path/"result").exists()
