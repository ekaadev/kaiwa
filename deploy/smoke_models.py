import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from _paths import BACKEND, HF_HOME, LOGS, load_runtime_env  # noqa: E402

sys.path.insert(0, str(BACKEND))
import asyncio, json, os, sys, time
from pathlib import Path
settings=load_runtime_env()
os.environ.update(settings)
os.environ["HF_HOME"]=str(HF_HOME)
from app.tutor import TutorConfig, build_tutor_processors, TUTOR_INSTRUCTIONS, QWEN_MODEL
from openai import OpenAI
config=TutorConfig.from_env()
results={"assets_present": config.assets_present()}
client=OpenAI(base_url=config.llm_base_url, api_key=config.llm_api_key)
try:
    t=time.monotonic()
    response=client.chat.completions.create(model=QWEN_MODEL, messages=[{"role":"system","content":TUTOR_INSTRUCTIONS},{"role":"user","content":"Hello! I want to practice Japanese. What should we talk about?"}], max_tokens=120, extra_body={"chat_template_kwargs":{"enable_thinking":False}}, timeout=45)
    results["qwen"]={"seconds":round(time.monotonic()-t,2),"text":response.choices[0].message.content,"tokens":response.usage.completion_tokens}
except Exception as exc:
    results["qwen_error"]=type(exc).__name__
try:
    t=time.monotonic()
    processors=build_tutor_processors(config)
    results["adaptive_pipeline"]={"loaded":True,"seconds":round(time.monotonic()-t,2)}
    import numpy as np
    phonemes,_=processors[4]._japanese_g2p("こんにちは。今日はどんなことを話したいですか。")
    samples,rate=processors[4]._kokoro.create(phonemes,voice="jf_alpha",is_phonemes=True)
    results["japanese_tts"]={"samples":len(samples),"rate":rate,"seconds":round(len(samples)/rate,2),"peak":float(np.max(np.abs(samples)))}
    audio=np.interp(np.arange(int(len(samples)*16000/rate))*rate/16000,np.arange(len(samples)),samples).astype(np.float32)
    from faster_whisper import WhisperModel
    model=WhisperModel(str(config.whisper_path),device="cpu",compute_type="int8",cpu_threads=2)
    t=time.monotonic()
    segments,info=model.transcribe(audio,beam_size=1)
    text="".join(segment.text for segment in segments)
    results["whisper"]={"language":info.language,"text":text,"seconds":round(time.monotonic()-t,2)}
except Exception as exc:
    results["pipeline_error"]={"type":type(exc).__name__,"message":str(exc)[:240]}
LOGS/"model-smoke.json".write_text(json.dumps(results,ensure_ascii=False,indent=2))
print(json.dumps(results,ensure_ascii=False,indent=2),flush=True)
