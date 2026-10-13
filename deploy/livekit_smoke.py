import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from _paths import BACKEND, HF_HOME, LOGS, load_runtime_env  # noqa: E402

sys.path.insert(0, str(BACKEND))
import asyncio, json, os, sys, time
from pathlib import Path
import httpx
import numpy as np
from livekit import rtc
settings=load_runtime_env()
os.environ.update(settings)
os.environ["LOGURU_LEVEL"]="INFO"
os.environ["OMP_NUM_THREADS"]="2"
os.environ["OPENBLAS_NUM_THREADS"]="2"
from kokoro_onnx import Kokoro
from misaki.ja import JAG2P

async def main():
    result={"test":"synthetic anonymous practice over LiveKit"}
    phonemes,_=JAG2P(version="pyopenjtalk")("こんにちは。日本語を練習したいです。")
    kokoro=Kokoro(settings["TUTOR_KOKORO_MODEL_PATH"],settings["TUTOR_KOKORO_VOICES_PATH"])
    samples,rate=await asyncio.to_thread(kokoro.create,phonemes,voice="jf_alpha",is_phonemes=True)
    pcm=np.concatenate([np.zeros(rate//2),samples,np.zeros(rate*4)])
    pcm=(np.clip(pcm,-1,1)*32767).astype(np.int16)
    room=rtc.Room()
    received=asyncio.Event()
    tasks=[]
    output_samples=0
    output_peak=0
    first_audio=None
    sent_at=None
    async def consume(track):
        nonlocal output_samples,output_peak,first_audio
        async for event in rtc.AudioStream(track,sample_rate=24000,num_channels=1):
            data=np.frombuffer(event.frame.data,dtype=np.int16)
            peak=int(np.max(np.abs(data.astype(np.int32))))
            if peak>100:
                output_samples+=len(data)
                output_peak=max(output_peak,peak)
                if first_audio is None:
                    first_audio=time.monotonic()
                if output_samples>=24000:
                    received.set()
    @room.on("track_subscribed")
    def on_track(track,publication,participant):
        if track.kind==rtc.TrackKind.KIND_AUDIO:
            tasks.append(asyncio.create_task(consume(track)))
    async with httpx.AsyncClient(base_url="http://127.0.0.1:8002",timeout=45) as client:
        response=await client.get("/v1/practice/readiness")
        result["readiness_http"]=response.status_code
        t=time.monotonic()
        response=await client.post("/v1/practice/calls",json={})
        result["start_http"]=response.status_code
        result["call_setup_seconds"]=round(time.monotonic()-t,2)
        if response.status_code!=201:
            result["start_error"]=response.json()
            return result
        call=response.json()
        source=None
        try:
            await asyncio.wait_for(room.connect(call["room_url"],call["join_token"]),timeout=25)
            result["client_connected"]=True
            source=rtc.AudioSource(rate,1)
            track=rtc.LocalAudioTrack.create_audio_track("synthetic-test-microphone",source)
            options=rtc.TrackPublishOptions(source=rtc.TrackSource.SOURCE_MICROPHONE)
            await room.local_participant.publish_track(track,options)
            await asyncio.sleep(1)
            sent_at=time.monotonic()
            step=rate//50
            for start in range(0,len(pcm),step):
                chunk=pcm[start:start+step]
                if len(chunk)<step:
                    chunk=np.pad(chunk,(0,step-len(chunk)))
                await source.capture_frame(rtc.AudioFrame(data=chunk.tobytes(),sample_rate=rate,num_channels=1,samples_per_channel=step))
            await source.wait_for_playout()
            result["input_speech_seconds"]=round(len(samples)/rate,2)
            await asyncio.wait_for(received.wait(),timeout=90)
            await asyncio.sleep(12)
            result["received_tutor_audio_seconds"]=round(output_samples/24000,2)
            result["received_audio_peak"]=output_peak
            result["first_audio_after_start_seconds"]=round(first_audio-sent_at,2)
            transcript=await client.get("/v1/practice/calls/"+call["call_id"]+"/transcript",headers={"Authorization":"Bearer "+call["transcript_token"]})
            result["transcript_http"]=transcript.status_code
            if transcript.status_code==200:
                result["transcript"]=transcript.json()
        except Exception as exc:
            result["error_type"]=type(exc).__name__
        finally:
            response=await client.post("/v1/practice/calls/"+call["call_id"]+"/end",json={},headers={"Authorization":"Bearer "+call["transcript_token"]})
            result["end_http"]=response.status_code
            finalized=await client.get("/v1/practice/calls/"+call["call_id"]+"/transcript",headers={"Authorization":"Bearer "+call["transcript_token"]})
            if finalized.status_code==200:
                result["final_transcript"]=finalized.json()
            await room.disconnect()
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks,return_exceptions=True)
            if source is not None:
                await source.aclose()
    return result

try:
    result=asyncio.run(main())
except Exception as exc:
    result={"error_type":type(exc).__name__}
(LOGS / "livekit-smoke.json").write_text(json.dumps(result,ensure_ascii=False,indent=2))
print(json.dumps(result,ensure_ascii=False,indent=2),flush=True)
