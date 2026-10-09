import math

from musicsheet_transcription_eval.contracts import Events,Note,Pedal


def test_event_hash_sorts_null_first_normalizes_negative_zero_and_preserves_duplicates():
    from musicsheet_transcription_eval.determinism import events_hash
    a,b=Note(60,-0.,1.,None),Note(60,0.,1.,80.)
    pedal=Pedal('sustain',.25,.75,127)
    assert events_hash(Events((a,b),(pedal,)))==events_hash(Events((b,Note(60,0.,1.,None)),(pedal,)))
    assert events_hash(Events((a,a,b),(pedal,)))!=events_hash(Events((a,b),(pedal,)))
    assert events_hash(Events((a,),()))!=events_hash(Events((Note(60,0.,1.,0.),),()))


def test_binary_hash_golden_and_one_bit_difference():
    import hashlib
    from musicsheet_transcription_eval.determinism import events_hash
    # Independent literal encoding: revision, N count1, pitch60/onset0/offset1/null, P count0.
    literal=bytes.fromhex('5730352d4556454e54532d31004e01000000000000000000000000004e400000000000000000000000000000f03f00500000000000000000')
    assert events_hash(Events((Note(60,0.,1.,None),),()))==hashlib.sha256(literal).hexdigest()
    assert events_hash(Events((Note(60,0.,1.,80.),),()))!=events_hash(Events((Note(60,0.,1.,math.nextafter(80.,math.inf)),),()))
