"""Synthetic Task4 inputs; no model, weights or network required."""
from dataclasses import asdict
import hashlib
import json
from pathlib import Path
import sys
import wave

import mido

BASIC_SOURCE = '049dc8a01a170c2370d7b246ec1c2067e060c3bf'
PIANO_SOURCE = '0226e74cbc805660e34bbd6a8fed2083890ebb88'
PIANO_OPTIONS = dict(onset_threshold=.3,offset_threshold=.3,frame_threshold=.1,
                     pedal_offset_threshold=.2,segment_samples=160000,sample_rate=16000)


def candidate(root,kind='basic_pitch'):
    from musicsheet_transcription_eval.contracts import Candidate
    root.mkdir(parents=True,exist_ok=True)
    lock,checkpoint=root/'uv.lock',root/'model.bin'
    lock.write_bytes(b'synthetic lock'); checkpoint.write_bytes(b'synthetic model')
    source=BASIC_SOURCE if kind=='basic_pitch' else PIANO_SOURCE
    runtime=dict(python_version=[3,12,13],package_version='0.4.0' if kind=='basic_pitch' else '0.0.6',
        source_commit=source,backend='onnx_cpu' if kind=='basic_pitch' else 'torch_cpu',backend_version='1.23.2' if kind=='basic_pitch' else '2.10.0+cpu',
        threads=None if kind=='basic_pitch' else dict(intra=1,interop=1))
    return Candidate(kind,Path(sys.executable),'cpu',checkpoint,hashlib.sha256(checkpoint.read_bytes()).hexdigest(),
        hashlib.sha256(lock.read_bytes()).hexdigest(),source,lock,runtime)


def output(root,kind='basic_pitch',*,checkpoint_sha='b'*64,input_sha='a'*64,notes=None):
    root.mkdir(parents=True)
    notes=notes if notes is not None else [dict(pitch=60,onset=3.,offset=4.,velocity=80)]
    if kind=='basic_pitch':
        wire=dict(schema_version=1,provider=dict(id='spotify-basic-pitch',package_version='0.4.0',
            source_commit=BASIC_SOURCE,model_asset='nmp.onnx',supports_pedal=False,
            confidence_semantics='uncalibrated_note_activation_mean'),
            note_events=[dict(note_id=f'bp-{i}',pitch=n['pitch'],onset_sec=n['onset'],offset_sec=n['offset'],
                velocity_prediction=None,activation=.8,amt_confidence=.8,source_chunk=None) for i,n in enumerate(notes)],pedal_events=[])
    else:
        wire=dict(schema_version=1,source_commit=PIANO_SOURCE,
            source_url='https://github.com/qiuqiangkong/piano_transcription_inference',package_version='0.0.6',
            model='Note_pedal',checkpoint_name='CRNN_note_F1=0.9677_pedal_F1=0.9186.pth',
            checkpoint_sha256=checkpoint_sha,input_sha256=input_sha,device='cpu',dtype='float32',
            options=PIANO_OPTIONS,runtime=dict(torch_num_threads=1,torch_num_interop_threads=1),
            duration_sec=30.,notes=notes,pedals=[])
    (root/'raw_transcription.json').write_text(json.dumps(wire),encoding='utf-8')
    midi=mido.MidiFile(type=0,ticks_per_beat=384); track=mido.MidiTrack();midi.tracks.append(track)
    track.append(mido.MetaMessage('set_tempo',tempo=500000,time=0))
    events=[]
    for n in notes:
        events.extend([(int(n['onset']*768),1,mido.Message('note_on',note=n['pitch'],velocity=n['velocity'])),
                       (int(n['offset']*768),0,mido.Message('note_off',note=n['pitch']))])
    previous=0
    for tick,_,message in sorted(events,key=lambda value:value[:2]):
        track.append(message.copy(time=tick-previous)); previous=tick
    track.append(mido.MetaMessage('end_of_track',time=0));midi.save(root/'transcription.mid')
    return wire


def entry(root,index=0):
    from musicsheet_transcription_eval.contracts import AudioPreparationReceipt,ManifestEntry
    root.mkdir(parents=True,exist_ok=True)
    for label,rate in (('basic',22050),('piano',16000)):
        with wave.open(str(root/f'{label}.wav'),'wb') as handle:
            handle.setparams((1,2,rate,0,'NONE','not compressed'));handle.writeframes(b'\0\0'*(rate*30))
    metric_ref=dict(events=dict(notes=[dict(pitch=60,onset=3.,offset=4.,velocity=80.)],pedals=[]),censored_count=0)
    reference=root/'reference.json';reference.write_text(json.dumps(dict(key_release=metric_ref,sustain=metric_ref)))
    receipt=AudioPreparationReceipt('a'*64,'b'*64,22050,661500,0,661500,480000,
        'ffmpeg version synthetic',(('ffmpeg','basic'),('ffmpeg','piano')),'w05-pcm-r2',.1)
    digest=lambda path:hashlib.sha256(path.read_bytes()).hexdigest()
    from musicsheet_transcription_eval.manifest import canonical_json
    return ManifestEntry(f'{index:064x}',f'2018/{index}.wav',f'2018/{index}.midi',0,'c'*64,'d'*64,
        root/'basic.wav',root/'piano.wav',digest(root/'basic.wav'),digest(root/'piano.wav'),reference,
        digest(reference),receipt,hashlib.sha256(canonical_json(asdict(receipt))).hexdigest())


def metric(tp=80,fp=20,fn=20):
    if tp+fn==0:return dict(tp=tp,fp=fp,fn=fn,precision=None,recall=None,f1=None)
    return dict(tp=tp,fp=fp,fn=fn,precision=tp/(tp+fp) if tp+fp else 0.,
                recall=tp/(tp+fn),f1=2*tp/(2*tp+fp+fn))


def selection_input():
    import copy
    models={}
    for kind in ('basic_pitch','piano_amt'):
        first={f'{i:064x}':dict(onset=metric(),sustain=metric(),key_release=metric(),
            velocity=dict(mae=None,pairs=[],reference_sorted=[],prediction_sorted=[]),
            censored=dict(reference_key_release=0,reference_sustain=0,predicted=0)) for i in range(12)}
        models[kind]=dict(first_runs=first,determinism={key:dict(status='deterministic_observed',
            hashes=['a'*64]*3,f1_range=[.8,.8]) for key in first},elapsed_sec=[10.]*36,
            not_run=0,operationally_ineligible=False,unresolved_failures=0)
    return copy.deepcopy(dict(schema_version=1,gates=[],models=models))
