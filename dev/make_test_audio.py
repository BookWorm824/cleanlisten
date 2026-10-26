import sherpa_onnx, soundfile as sf, numpy as np, subprocess, sys, os
os.makedirs("test/Bully Folder", exist_ok=True)
d=sys.argv[1] if len(sys.argv) > 1 else "models/vits-piper-en_US-lessac-medium/"  # Piper voice folder
tts=sherpa_onnx.OfflineTts(sherpa_onnx.OfflineTtsConfig(model=sherpa_onnx.OfflineTtsModelConfig(
    vits=sherpa_onnx.OfflineTtsVitsModelConfig(model=d+"en_US-lessac-medium.onnx",tokens=d+"tokens.txt",data_dir=d+"espeak-ng-data"),num_threads=2)))
P=["Chapter Nine.",
 "Detective Hollis walked into the diner just after noon.",
 "At the counter, the waitress flirted with a trucker and laughed at his jokes.",
 "Hollis ordered coffee and opened his notebook.",
 "In the corner booth, two teenage boys cornered a smaller kid.",
 "You're such a loser, one of them sneered. Nobody likes you.",
 "Hollis stood up, and the boys ran out the door.",
 "Screw you, old man, the taller one shouted from the parking lot.",
 "Later, at the bar, Mark was flirting with him all night, but Hollis only wanted answers.",
 "He picked up a screw from the floor and set it on the table.",
 "He felt like an idiot for missing the clue."]
ch=[]
for p in P:
    a=tts.generate(p,sid=0,speed=1.0); ch+=[np.array(a.samples,dtype=np.float32),np.zeros(int(a.sample_rate*0.6),dtype=np.float32)]
sf.write("test/tmp.wav",np.concatenate(ch),a.sample_rate)
subprocess.run(["ffmpeg","-y","-v","error","-i","test/tmp.wav","-b:a","64k","test/Bully Folder/Chapter Nine.mp3"],check=True); print("ok")
