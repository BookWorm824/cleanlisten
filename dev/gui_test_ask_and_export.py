import importlib.machinery, importlib.util, os, sys, json, subprocess
os.environ["LOCALAPPDATA"]="test/appdata17"
os.environ["USERPROFILE"]="test/home"
os.environ["PATH"]="dev/fakeclaude:"+os.environ["PATH"]
loader=importlib.machinery.SourceFileLoader("gui","CleanListen.pyw")
spec=importlib.util.spec_from_loader("gui",loader); gui=importlib.util.module_from_spec(spec); loader.exec_module(gui)
gui.filedialog.askdirectory=lambda **k: os.path.abspath("test/Bully Folder")
gui.messagebox.showerror=lambda *a, **k: print("ERROR:", a)
gui.messagebox.showinfo=lambda *a, **k: print("INFO:", a[1][:80].replace("\n"," "))
import cleanlisten_claude as cc, cleanlisten as E
app=gui.App()
def shot(n): app.update(); subprocess.run(["import","-window","root",f"test/shots/{n}.png"])
def title():
    try: return [w for w in app.page.winfo_children() if isinstance(w, gui.tk.Label)][0].cget("text")
    except Exception: return ""
def wait(t, fn):
    def c():
        if title()==t: fn()
        else: app.after(300, c)
    app.after(300, c)
def find(widget, cls, pred=lambda w: True):
    out=[]
    for ch in widget.winfo_children():
        if isinstance(ch, cls) and pred(ch): out.append(ch)
        out += find(ch, cls, pred)
    return out
def s1(): app.pick_folder(); app.ai_var.set(False); app.claude_var.set(False); app.start(); wait("Review before saving", s2)
def s2():
    a=app.analysis; asr=E.load_asr(app.workdir, a["parts"])
    a["scenes"]=[]; cc._add_passage(a, asr, 1, 5, "ref", True, "", "", src="you")
    app._save_analysis(); app.show_review()
    txt=[t for t in find(app.page, gui.tk.Text) if "waitress" in t.get("1.0","end")][0]
    i=txt.search("At the counter", "1.0"); txt.tag_add("sel", i, f"{i} + 40c")
    link=find(app.page, gui.tk.Label, lambda w: str(w.cget("text")).startswith("Ask Claude about"))[0]
    print("link:", link.cget("text"), "| open before:", getattr(link, "_open", None))
    app._ask_inline(link.master, app.analysis["scenes"][0], txt, link, "P"); app.update()
    print("entries:", len(find(app.page, gui.ttk.Entry)), "buttons:", [str(b.cget("text")) for b in find(app.page, gui.ttk.Button)][-4:])
    ent=find(app.page, gui.ttk.Entry)[-1]; ent.insert(0, "just cut this line")
    shot("19_1_asking")
    find(app.page, gui.ttk.Button, lambda w: str(w.cget("text"))=="Send")[-1].invoke()
    app.after(500, s3)
def s3():
    sc=app.analysis["scenes"][0]
    if not sc.get("chat_answer"): app.after(400, s3); return
    print("passage now: %.0f sec | cut=%s | %s |" % (sc["e"]-sc["s"], sc["cut"], sc.get("ai_note")), sc["text"])
    print("answer on card:", sc["chat_answer"][:120].replace("\n"," / "))
    print("undo button:", bool(find(app.page, gui.ttk.Button, lambda w: str(w.cget("text")).startswith("Undo"))))
    shot("19_2_after")
    app._save_from_review(); wait("All done!", s4)
def s4():
    shot("19_3_done")
    find(app.page, gui.ttk.Button, lambda w: str(w.cget("text")).startswith("Export what we refined"))[0].invoke()
    d=os.environ["USERPROFILE"]+"/Desktop"; f=[x for x in os.listdir(d) if x.startswith("CleanListen refined")][0]
    j=json.load(open(d+"/"+f)); print("export:", f, "| items:", len(j["items"]), "| chat:", j["chat"][:2])
    app.destroy()
app.after(800, s1); app.after(250000, app.destroy); app.mainloop()
