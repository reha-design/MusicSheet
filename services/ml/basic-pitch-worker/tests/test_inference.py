from pathlib import Path

from musicsheet_basic_pitch_worker.inference import InferenceError, run_prediction


def test_prediction_output_is_redirected_to_stderr(tmp_path: Path, monkeypatch, capsys):
    audio_path = tmp_path / "piano.wav"

    def fake_predict(path):
        print("Basic Pitch progress")
        return object(), None, [(0.0, 0.5, 60, 0.75, [])]

    monkeypatch.setattr("basic_pitch.inference.predict", fake_predict)

    prediction = run_prediction(audio_path)
    captured = capsys.readouterr()

    assert captured.out == ""
    assert "Basic Pitch progress" in captured.err
    assert prediction.note_events == [(0.0, 0.5, 60, 0.75, [])]


def test_prediction_wraps_upstream_errors_as_inference_error(tmp_path: Path, monkeypatch):
    def fail_prediction(_path):
        raise RuntimeError("model failed")

    monkeypatch.setattr("basic_pitch.inference.predict", fail_prediction)

    try:
        run_prediction(tmp_path / "piano.wav")
    except InferenceError as error:
        assert "model failed" in str(error)
    else:
        raise AssertionError("run_prediction should raise InferenceError")
