import asyncio
import gc
import hashlib
import json
import time
import warnings

import httpx
import pytest


@pytest.fixture
def service(monkeypatch):
    from musicsheet_transcription_eval import checkpoint
    real_client, real_async_client = httpx.Client, httpx.AsyncClient
    body = b"abcd"
    monkeypatch.setattr(checkpoint,"CHECKPOINT_BYTES",len(body))
    monkeypatch.setattr(checkpoint,"CHECKPOINT_MD5",hashlib.md5(body).hexdigest())
    metadata=dict(id=4034264,metadata=dict(license=dict(id="cc-by-4.0")),files=[dict(
        key=checkpoint.CHECKPOINT_NAME,size=4,checksum="md5:"+hashlib.md5(body).hexdigest(),
        links=dict(self="https://zenodo.org/api/records/4034264/files/"+checkpoint.CHECKPOINT_NAME+"/content"))])
    calls=[]
    options=dict(metadata=metadata,body=body,status=200,encoding="identity",delay_stage=None,
        streams=[],clients=[],late_yields=0,loop=None)

    class Stream(httpx.SyncByteStream,httpx.AsyncByteStream):
        def __init__(self,data,paused):
            self.data,self.paused,self.closed=data,paused,False
            options["streams"].append(self)
        def __iter__(self):
            if self.paused:
                yield self.data[:1]
                time.sleep(.5)
                options["late_yields"]+=1
                yield self.data[1:]
            else: yield self.data
        async def __aiter__(self):
            if self.paused:
                yield self.data[:1]
                await asyncio.sleep(.5)
                options["late_yields"]+=1
                yield self.data[1:]
            else: yield self.data
        def close(self): self.closed=True
        async def aclose(self): self.closed=True

    def record(request):
        calls.append(request)
        assert "authorization" not in request.headers and "cookie" not in request.headers
        assert request.headers["accept-encoding"] == "identity"

    def response(request):
        if request.url.path.endswith("/4034264"):
            return httpx.Response(200,stream=Stream(json.dumps(options["metadata"]).encode(),options["delay_stage"]=="metadata_body"))
        return httpx.Response(options["status"],stream=Stream(options["body"],options["delay_stage"]=="weights_body"),
            headers={"content-encoding":options["encoding"],"content-length":str(len(options["body"]))})

    def handle(request):
        record(request)
        if options["delay_stage"]=="headers" and request.url.path.endswith("/4034264"): time.sleep(.5)
        return response(request)

    async def async_handle(request):
        options["loop"]=asyncio.get_running_loop()
        record(request)
        if options["delay_stage"]=="headers" and request.url.path.endswith("/4034264"): await asyncio.sleep(.5)
        return response(request)

    def client(**kwargs):
        assert kwargs["trust_env"] is False and kwargs["follow_redirects"] is False and kwargs["timeout"] == 60
        instance=real_client(transport=httpx.MockTransport(handle),**kwargs)
        options["clients"].append(instance)
        return instance
    def async_client(**kwargs):
        assert kwargs["trust_env"] is False and kwargs["follow_redirects"] is False and kwargs["timeout"] == 60
        instance=real_async_client(transport=httpx.MockTransport(async_handle),**kwargs)
        options["clients"].append(instance)
        return instance
    monkeypatch.setattr(checkpoint.httpx,"Client",client)
    monkeypatch.setattr(checkpoint.httpx,"AsyncClient",async_client)
    return checkpoint,options,calls


def test_official_metadata_download_hash_and_valid_cache_without_network(tmp_path,service):
    checkpoint,options,calls=service
    root=tmp_path/"models"
    receipt=checkpoint.prepare_checkpoint(root)
    assert receipt["size_bytes"] == 4 and receipt["sha256"] == hashlib.sha256(options["body"]).hexdigest()
    assert receipt["md5"] == hashlib.md5(options["body"]).hexdigest() and receipt["license"] == "CC-BY-4.0"
    assert (root/checkpoint.CHECKPOINT_NAME).read_bytes() == options["body"]
    assert len(calls)==2
    cached=checkpoint.prepare_checkpoint(root)
    assert cached["sha256"] == receipt["sha256"] and len(calls)==2
    assert not list(root.glob("*.part"))


@pytest.mark.parametrize("case", ["record","license","size","md5","url","redirect","gzip","truncated","corrupt","excess"])
def test_invalid_metadata_or_transfer_leaves_no_owned_partial(tmp_path,service,case):
    checkpoint,options,calls=service
    root=tmp_path/"models"
    root.mkdir()
    existing=root/"keep.part"
    existing.write_text("keep")
    file=options["metadata"]["files"][0]
    if case=="record": options["metadata"]["id"]=0
    elif case=="license": options["metadata"]["metadata"]["license"]["id"]="unknown"
    elif case=="size": file["size"]=3
    elif case=="md5": file["checksum"]="md5:"+"0"*32
    elif case=="url": file["links"]["self"]="https://secret-sentinel.example/weights"
    elif case=="redirect": options["status"]=302
    elif case=="gzip": options["encoding"]="gzip"
    elif case=="truncated": options["body"]=b"abc"
    elif case=="corrupt": options["body"]=b"abce"
    elif case=="excess": options["body"]=b"abcde"
    with pytest.raises(ValueError) as error:
        checkpoint.prepare_checkpoint(root)
    assert "secret-sentinel" not in str(error.value)
    assert existing.read_text()=="keep"
    assert sorted(p.name for p in root.iterdir()) == ["keep.part"]


def test_existing_bad_checkpoint_is_not_overwritten(tmp_path,service):
    checkpoint,options,calls=service
    root=tmp_path/"models"
    receipt=checkpoint.prepare_checkpoint(root)
    target=root/checkpoint.CHECKPOINT_NAME
    target.write_bytes(b"abce")
    with pytest.raises(ValueError):
        checkpoint.prepare_checkpoint(root)
    assert target.read_bytes()==b"abce" and len(calls)==2


@pytest.mark.parametrize("limit", ["METADATA_LIMIT", "TRANSFER_LIMIT", "TOTAL_SECONDS"])
def test_resource_caps_and_deadline_cleanup(tmp_path,service,monkeypatch,limit):
    checkpoint, _, _ = service
    monkeypatch.setattr(checkpoint,limit,0)
    with pytest.raises(ValueError): checkpoint.prepare_checkpoint(tmp_path/"models")
    assert not list(tmp_path.rglob("*.part"))


@pytest.mark.parametrize("stage", ["headers","metadata_body","weights_body"])
def test_deadline_interrupts_inflight_requests_and_cleans_owned_files(tmp_path,service,monkeypatch,stage):
    checkpoint,options,calls=service
    root=tmp_path/"models"
    root.mkdir()
    marker=root/"keep.part"
    marker.write_text("keep")
    options["delay_stage"]=stage
    monkeypatch.setattr(checkpoint,"TOTAL_SECONDS",.1)
    started=time.monotonic()
    with pytest.raises(ValueError): checkpoint.prepare_checkpoint(root)
    elapsed=time.monotonic()-started
    assert elapsed < .4 and options["late_yields"] == 0
    assert calls and all(client.is_closed for client in options["clients"])
    assert all(stream.closed for stream in options["streams"])
    assert options["loop"].is_closed() and not asyncio.all_tasks(options["loop"])
    assert marker.read_text()=="keep" and sorted(p.name for p in root.iterdir())==["keep.part"]


def test_uncached_sync_entry_rejects_active_loop_before_coroutine_network_or_file(tmp_path,service,monkeypatch):
    checkpoint,options,calls=service
    coroutines=[]
    def forbidden(*args,**kwargs):
        coroutines.append(True)
        pytest.fail("Active loop created download coroutine")
    monkeypatch.setattr(checkpoint,"_prepare_download",forbidden,raising=False)
    async def attempt():
        with pytest.raises(ValueError,match="synchronous preparation required"):
            checkpoint.prepare_checkpoint(tmp_path/"models")
    with warnings.catch_warnings(record=True) as seen:
        warnings.simplefilter("always")
        asyncio.run(attempt())
        gc.collect()
    assert not coroutines and not calls and not options["clients"] and not list(tmp_path.iterdir())
    assert not [w for w in seen if issubclass(w.category,RuntimeWarning)]
