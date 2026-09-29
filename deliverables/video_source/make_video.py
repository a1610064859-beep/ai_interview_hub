"""Reproducible narrated 1080p demo. Requires Pillow, FFmpeg, project edge_tts.
Run: python deliverables/video_source/make_video.py --prepare
Then: python deliverables/video_source/make_video.py --render
"""
from __future__ import annotations
import argparse, concurrent.futures, hashlib, json, math, os, re, subprocess
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "deliverables"
ASSETS = OUT / "video_assets"
WORK = ROOT / "tmp" / "video"
SOURCE = OUT / "video_source"
FINAL = OUT / "智驾未来_AI面试仓_命题05演示.mp4"
TTS_PY = Path(os.environ.get("VIDEO_TTS_PYTHON", ROOT / ".venv" / "Scripts" / "python.exe"))
W, H, FPS = 1920, 1080, 25
BG, PANEL, INK, MUTED = "#07131e", "#102434", "#eef8ff", "#a7bccb"
CYAN, ORANGE, LINE = "#65e1e7", "#ffb477", "#244253"
FONT = "C:/Windows/Fonts/msyh.ttc"
BOLD = "C:/Windows/Fonts/msyhbd.ttc"

SCENES = [
 dict(key="opening",chapter="01 / 开场",title="一次面试，不止一个分数",lead="从回答到成长",labels=[],image="edge_jobs.png",diagram="triple",voice="如果一次面试只留下一个分数，学生下一次该怎么练？智驾未来给出另一种答案：从看见岗位，到开口回答，再到带着证据复盘，每一步都能找到下一步。"),
 dict(key="jobs",chapter="02 / 选定目标",title="先选岗位，再练真问题",lead="智驾测试与三电系统测试",labels=[],image="edge_jobs.png",diagram="jobs",voice="从智驾测试和三电系统测试出发，题目把车辆感知、总线通信、电池管理带进岗位语境。两道通用题、三道专业题、一道情景题，练的是工作现场真正会遇到的思考。"),
 dict(key="interview",chapter="03 / 进入面试舱",title="答完一题，保存一题",lead="提问、回答、追问、断点续答",labels=[],image="edge_interview.png",diagram="flow",voice="走进面试舱，问题在屏幕上展开。系统语音提问，学生可以开口回答，也能用文本练习。每完成一题，回答和进度立即保存；页面刷新，仍能从当前题继续。需要深入时，面试官还会追问一次。"),
 dict(key="acoustic",chapter="04 / 声学观察",title="表达节奏，也看得见",lead="语速、停顿、填充词",labels=[],image="edge_report_detail.png",diagram="acoustic",voice="表达不必只凭感觉。这份真实报告记录了每分钟一百七十八字的语速、二点三次停顿和二点六次填充词。数字让节奏问题变得具体，也为下一次练习指出方向。"),
 dict(key="report",chapter="05 / 能力报告",title="七十九点二分之后，还有为什么",lead="真实会话 #6 · 报告 #4",labels=[],image="edge_report_top.png",diagram="report",voice="这不是一张只会给分的成绩单。真实会话六得到七十九点二分，雷达图让优势和待补点一眼可见。每个维度旁边，都能找到解释和回答中的原话。"),
 dict(key="evidence",chapter="06 / 原话证据",title="把建议落到下一次回答",lead="证据、原因、改进建议",labels=[],image="edge_report_detail.png",diagram="evidence",voice="看见原话，才知道怎么改。系统核对引用是否真的出自回答，再给出具体建议；如果是文本训练，没有声音数据的维度就留空。认真评价，也认真对待不知道的部分。"),
 dict(key="growth",chapter="07 / 成长记录",title="下一次训练，从上一次出发",lead="同人同岗、共同维度变化",labels=[],image="edge_growth.png",diagram="growth",voice="第二次训练回来，成长页有了两点连成的线。专业、逻辑、岗位素养三项共同有效维度，模型观测均分从七十五到九十四点二。表达流畅度没有可比数据就留白；打开原报告，下一题该怎么练更清楚。"),
 dict(key="learning",chapter="08 / 面试学习",title="先学会讲，再大胆练",lead="从听题到讲清真实经历",labels=[],image="edge_learn.png",diagram="learning",voice="第一次面对面试题，不必急着背模板。先听懂考官在问什么，再把自己的真实经历讲清楚。经历题可以借助 STAR，知识题就先给依据、再做判断；不会的题，也能诚实而清楚地回应。"),
 dict(key="counsel",chapter="09 / 新生路径",title="把兴趣接到具体岗位",lead="岗位地图与学习路径",labels=[],image="edge_counsel_result.png",diagram="counsel",voice="新生填入专业、年级和兴趣，岗位地图便把智驾与三电的方向铺开：要补哪些技能、先做什么项目、下一学期怎么准备。看完路径，点一下就能进入对应岗位训练。"),
 dict(key="enterprise",chapter="10 / 企业初筛",title="候选卡片，能回到原始报告",lead="同源会话与岗位加权",labels=[],image="edge_recruiter_candidates.png",diagram="enterprise",voice="企业看板上的候选人，不是另做一份静态排行榜。卡片取自学生已经完成的会话和报告，在同岗位、同评分口径下加权排序。打开原报告，判断就有据可查。"),
 dict(key="architecture",chapter="11 / 技术链路",title="每一步，都有系统支撑",lead="逐题落库、本地语音与可解释评分",labels=[],image="edge_interview.png",diagram="architecture",voice="眼前这条体验链，由 Next.js 负责交互，FastAPI 编排问题与追问，SQLite 逐题保存。本地语音识别提取回答，评分再核对原话证据。界面上的顺畅，来自后端每一步都接得住。"),
 dict(key="closing",chapter="12 / 结尾",title="让每一次回答，都成为下一步",lead="智驾未来 · AI 面试仓",labels=[],image="edge_report_top.png",diagram="triple",voice="从认识岗位，到敢于回答；从一份报告，到更有方向的下一次练习。学生收获反馈，新生看见路径，企业核对依据。智驾未来，让面试不止于一次面试。"),
]

def run(args,**kwargs):
 result=subprocess.run([str(x) for x in args],stdout=subprocess.PIPE,stderr=subprocess.PIPE,**kwargs)
 if result.returncode: raise RuntimeError(result.stderr.decode("utf-8","replace")[-5000:])
 return result.stdout

def duration(path):
 return float(run(["ffprobe","-v","error","-show_entries","format=duration","-of","default=noprint_wrappers=1:nokey=1",path]))

def font(size,bold=False): return ImageFont.truetype(BOLD if bold else FONT,size)

def write(d,xy,text,size,fill=INK,bold=False,width=None,spacing=15):
 x,y=xy; f=font(size,bold); lines=[]
 for para in text.split("\n"):
  line=""
  for ch in para:
   if width and d.textlength(line+ch,font=f)>width and line: lines.append(line);line=ch
   else: line+=ch
  lines.append(line)
 for line in lines: d.text((x,y),line,font=f,fill=fill);y+=size+spacing
 return y

def pill(d,xy,text,size=25,fill=CYAN):
 x,y=xy;tw=int(d.textlength(text,font=font(size)))
 d.rounded_rectangle((x,y,x+tw+42,y+53),radius=26,fill="#132d3b",outline=LINE,width=1)
 write(d,(x+21,y+8),text,size,fill)

def card(d,rect,title,body,accent=CYAN):
 x,y,r,b=rect
 d.rounded_rectangle(rect,radius=22,fill=PANEL,outline=LINE,width=2)
 d.rounded_rectangle((x+24,y+27,x+30,b-26),radius=3,fill=accent)
 write(d,(x+54,y+24),title,34,INK,True,width=r-x-80)
 write(d,(x+54,y+88),body,25,MUTED,width=r-x-80,spacing=11)

def render_diagram(d,kind):
 x,y=1090,177;right=1800
 write(d,(x,127),"功能示意" if kind=="enterprise" else "机制示意",24,ORANGE if kind=="enterprise" else CYAN)
 data={
 "triple":[("01  新生","理解岗位  /  规划学习"),("02  学生","真实训练  /  反馈复盘"),("03  企业","同源报告  /  核对依据")],
 "architecture":[("交互层","Next.js · 语音输入 · 报告展示"),("服务层","FastAPI · 编排 · 评分 · 反馈"),("基础层","SQLite · 本地 ASR · TTS · LLM")],
 "enterprise":[("学生会话","训练完成并生成真实报告"),("资格筛选","同岗位 · 同学生 · 可比口径"),("候选记录","加权排序 → 回看原报告")],
 "acoustic":[("178 字 / 分","语速 · 观测值"),("2.3 次 / 分","停顿频率 · 观测值"),("2.6 次 / 分","填充词频率 · 观测值")],
 "evidence":[("01  引用","证据来自本场原始回答"),("02  校验","缺失信息保持 null"),("03  反馈","有效维度形成可解释建议")],
 "jobs":[("智驾测试","专业术语与岗位要求"),("三电系统测试","真实工作情景"),("6 道主问题","固定 2 + 专业 3 + 情景 1")],
 "flow":[("01  朗读问题","TTS 提问与进度显示"),("02  提交回答","音频转写或文本输入"),("03  继续训练","追问 / 下一题 / 生成报告")]}
 for i,(title,body) in enumerate(data.get(kind,data["triple"])):
  card(d,(x,y+i*228,right,y+185+i*228),title,body,CYAN if i!=2 else ORANGE)
  if i<2:d.line((x+354,y+193+i*228,x+354,y+217+i*228),fill=CYAN,width=3)

def render_scene(scene,idx):
 im=Image.new("RGB",(W,H),BG);d=ImageDraw.Draw(im)
 for yy in range(H):
  t=yy/H;d.line((0,yy,W,yy),fill=(7+int(3*t),19+int(8*t),30+int(12*t)))
 d.rounded_rectangle((145,91,1775,1009),radius=25,fill="#122e43",outline=CYAN,width=2)
 write(d,(158,25),scene["chapter"],23,CYAN,True)
 write(d,(465,17),scene["title"].replace("\n"," · "),39,INK,True,width=1220)
 write(d,(1690,30),f"{idx+1:02d}/{len(SCENES):02d}",23,ORANGE)
 d.line((160,82,1760,82),fill=LINE,width=2)
 d.line((160,82,160+round(1600*(idx+1)/len(SCENES)),82),fill=CYAN,width=4)
 path=ASSETS/scene["image"] if scene.get("image") else None
 if path and path.exists():
  src=Image.open(path).convert("RGB")
  src.thumbnail((1600,900),Image.Resampling.LANCZOS)
  sx=160+(1600-src.width)//2;sy=100+(900-src.height)//2
  im.paste(src,(sx,sy))
  scene["visual_type"]="real_page_screenshot";scene["image_sha256"]=hashlib.sha256(path.read_bytes()).hexdigest()
 else:render_diagram(d,scene["diagram"]);scene["visual_type"]="labeled_mechanism_illustration"
 d.rounded_rectangle((159,1009,1761,1074),radius=20,fill="#030c15",outline=LINE,width=1)
 dest=WORK/f"{idx:02d}_{scene['key']}.png";im.save(dest);return dest

def tts_one(pair):
 idx,scene=pair;target=ASSETS/f"narration_{idx:02d}.mp3";txt=SOURCE/f"narration_{idx:02d}.txt"
 txt.write_text(scene["voice"],encoding="utf-8")
 fingerprint=hashlib.sha256((scene["voice"]+"zh-CN-XiaoxiaoNeural+8%").encode()).hexdigest();marker=ASSETS/f"narration_{idx:02d}.sha256"
 if not target.exists() or not marker.exists() or marker.read_text()!=fingerprint:
  tts_env=os.environ.copy()
  if os.environ.get("VIDEO_TTS_PYTHON"):
   tts_env["PYTHONPATH"]=str(ROOT/".venv"/"Lib"/"site-packages")+os.pathsep+tts_env.get("PYTHONPATH","")
  run([TTS_PY,"-m","edge_tts","--voice","zh-CN-XiaoxiaoNeural","--rate=+8%","--file",txt,"--write-media",target],timeout=150,env=tts_env)
  marker.write_text(fingerprint)
 scene["audio"]=str(target.relative_to(ROOT)).replace("\\","/")
 scene["speech_duration"]=duration(target);scene["duration"]=math.ceil((scene["speech_duration"]+1.3)*FPS)/FPS
 print(f"Narration {idx+1:02d}: {scene['speech_duration']:.2f}s",flush=True)

def subtitle_parts(text):
 phrases=re.findall(r"[^，。；！？]+[，。；！？]?",text);pieces=[];current=""
 for phrase in phrases:
  if len(current+phrase)>29 and current:pieces.append(current.rstrip("，。；"));current=""
  if len(phrase)>29:
   if current:pieces.append(current.rstrip("，。；"));current=""
   for at in range(0,len(phrase),29):pieces.append(phrase[at:at+29].rstrip("，。；"))
  else:current+=phrase
 if current:pieces.append(current.rstrip("，。；"))
 return pieces

def stamp(seconds,ass=False):
 if ass:
  c=round(seconds*100);return f"{c//360000}:{c//6000%60:02}:{c//100%60:02}.{c%100:02}"
 m=round(seconds*1000);return f"{m//3600000:02}:{m//60000%60:02}:{m//1000%60:02},{m%1000:03}"

def subtitles(scenes):
 srt=[];events=[];offset=0;index=1
 for scene in scenes:
  chunks=subtitle_parts(scene["voice"]);total=sum(len(x) for x in chunks);at=offset+.4
  for chunk in chunks:
   end=at+scene["speech_duration"]*len(chunk)/total
   srt.append(f"{index}\n{stamp(at)} --> {stamp(end)}\n{chunk}\n")
   events.append(f"Dialogue: 0,{stamp(at,True)},{stamp(end,True)},Default,,0,0,0,,{chunk}")
   at=end;index+=1
  scene["start"]=offset;offset+=scene["duration"]
 (SOURCE/"智驾未来_演示字幕.srt").write_text("\n".join(srt),encoding="utf-8-sig")
 header="""[Script Info]
ScriptType: v4.00+
PlayResX: 1920
PlayResY: 1080
WrapStyle: 2

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,Microsoft YaHei,34,&H00F8FAFF,&H00FFFFFF,&H00000000,&H00000000,0,0,0,0,100,100,0,0,1,0,0,2,170,170,24,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
 (WORK/"captions.ass").write_text(header+"\n".join(events)+"\n",encoding="utf-8")
 (SOURCE/"storyboard.json").write_text(json.dumps(dict(width=W,height=H,fps=FPS,voice="zh-CN-XiaoxiaoNeural",date="2026-09-29",duration=offset,scenes=scenes),ensure_ascii=False,indent=2),encoding="utf-8")
 return offset

def render_clip(pair):
 idx,scene=pair;frame=render_scene(scene,idx);target=WORK/f"clip_{idx:02d}.mp4";t=scene["duration"]
 vf=f"fade=t=in:st=0:d=0.28,fade=t=out:st={t-.28:.2f}:d=0.28"
 run(["ffmpeg","-hide_banner","-loglevel","error","-y","-loop","1","-framerate",FPS,"-i",frame,"-i",ROOT/scene["audio"],"-vf",vf,"-af","adelay=400|400,apad,loudnorm=I=-16:TP=-1.5:LRA=9","-t",t,"-c:v","libx264","-preset","fast","-crf","20","-pix_fmt","yuv420p","-r",FPS,"-c:a","aac","-b:a","160k","-ar","48000","-movflags","+faststart",target])
 print(f"Rendered {idx+1:02d}: {target.name}",flush=True);return target

def main():
 p=argparse.ArgumentParser();p.add_argument("--prepare",action="store_true");p.add_argument("--render",action="store_true");p.add_argument("--frames-only",action="store_true");p.add_argument("--rerender",type=int,help="Regenerate one zero-based scene, then reassemble existing clips");args=p.parse_args()
 WORK.mkdir(parents=True,exist_ok=True);ASSETS.mkdir(parents=True,exist_ok=True)
 if args.frames_only:
  for idx,scene in enumerate(SCENES):render_scene(scene,idx)
  print("Frames prepared");return
 with concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool:list(pool.map(tts_one,enumerate(SCENES)))
 total=subtitles(SCENES);print(f"Total duration: {total:.2f}s",flush=True)
 if args.prepare and not args.render:return
 if args.rerender is not None:
  for idx,scene in enumerate(SCENES):render_scene(scene,idx)
  render_clip((args.rerender,SCENES[args.rerender]))
  clips=[WORK/f"clip_{idx:02d}.mp4" for idx in range(len(SCENES))]
 else:
  with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:clips=list(pool.map(render_clip,enumerate(SCENES)))
 subtitles(SCENES);concat=WORK/"concat.txt"
 concat.write_text("\n".join("file '"+str(x).replace("\\","/")+"'" for x in clips),encoding="utf-8")
 assembled=WORK/"assembled.mp4"
 run(["ffmpeg","-hide_banner","-loglevel","error","-y","-f","concat","-safe","0","-i",concat,"-c","copy",assembled])
 run(["ffmpeg","-hide_banner","-loglevel","error","-y","-i",assembled,"-vf","ass=captions.ass","-c:v","libx264","-preset","fast","-crf","20","-pix_fmt","yuv420p","-r",FPS,"-c:a","copy","-movflags","+faststart",FINAL],cwd=WORK)
 probe=json.loads(run(["ffprobe","-v","error","-show_format","-show_streams","-of","json",FINAL]))
 (SOURCE/"video_probe.json").write_text(json.dumps(probe,ensure_ascii=False,indent=2),encoding="utf-8")
 print(f"DONE: {FINAL} ({FINAL.stat().st_size/1024/1024:.2f} MiB)",flush=True)

if __name__=="__main__":main()
