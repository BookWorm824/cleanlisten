import importlib.machinery, importlib.util, os, subprocess, sys, json
os.environ["LOCALAPPDATA"]="test/appdata14"
os.environ["USERPROFILE"]="test/home"
os.environ["PATH"]="dev/fakeclaude:"+os.environ["PATH"]
loader=importlib.machinery.SourceFileLoader("gui","CleanListen.pyw")
spec=importlib.util.spec_from_loader("gui",loader); gui=importlib.util.module_from_spec(spec); loader.exec_module(gui)
gui.filedialog.askdirectory=lambda **k: os.path.abspath("test/Bully Folder")
gui.messagebox.showerror=lambda *a, **k: (print("ERROR:", a), app.destroy())
gui.messagebox.showinfo=lambda *a, **k: print("INFO:", a[1][:90].replace("\n"," "))
gui.open_path=lambda p: print("OPEN:", os.path.basename(p))
app=gui.App()
def shot(n): app.update(); subprocess.run(["import","-window","root",f"test/shots/{n}.png"])
def title():
    try: return [w for w in app.page.winfo_children() if isinstance(w, gui.tk.Label)][0].cget("text")
    except Exception: return ""
def state():
    a=app.analysis
    return [(s["kind"], s["cut"], s.get("ai_note"), s["text"][:30]) for s in a["scenes"]] + [("W", m["on"], m.get("note"), m.get("word_raw")) for m in a["mutes"]]
step=[0]
def go(fn, wait_title="Review before saving"):
    def w():
        if title()==wait_title: fn()
        else: app.after(400, w)
    app.after(400, w)
def s1():
    app.provider_var.set("claude"); app._provider_changed()
    app.pick_folder(); app.opts["bully"].set(True); app.opts["flirt"].set(True); app.ai_var.set(False); app.claude_var.set(True)
    app.after(1500, lambda: (shot("15_1_setup"), app.start(), go(s2)))
def s2():
    print("1st run:", *state(), sep="\n  ")
    print("visible scenes:", len(app.scene_vars), "visible words:", len(app.mute_vars))
    shot("15_2_review_default")
    app._sync_ticks(); app.view_mode = "all"; app.show_review(); shot("15_3_review_all")
    print("with fine shown:", len(app.scene_vars), len(app.mute_vars))
    app._sync_ticks(); app.view_mode = "list"; app.show_review()
    # untick 'Screw you' by hand, then re-run Claude: it must stay unticked
    for v, m in app.mute_vars:
        if (m.get("word_raw") or "").lower().startswith("screw"): v.set(False)
    app.claude_check(); go(s3)
def s3():
    sm=[m for m in app.analysis["mutes"] if (m.get("word_raw") or "").lower().startswith("screw")][0]
    print("after re-check, Screw you on:", sm["on"], "| note:", sm.get("note"), "| by_you:", sm.get("by_you"))
    app.open_all_text(); w=app.all_text_win
    ent=[c for c in w.winfo_children()[2].winfo_children() if isinstance(c, gui.ttk.Entry)][0]
    ent.insert(0, "coffee"); app.update()
    lb=[c for c in w.winfo_children()[4].winfo_children() if isinstance(c, gui.tk.Listbox)][0]
    print("search hits:", lb.size(), lb.get(0)[:60]); lb.selection_set(0)
    [b for b in w.winfo_children()[3].winfo_children() if isinstance(b, gui.ttk.Button)][0].invoke()
    app.update(); w.geometry("+0+0"); shot("15_4_alltext"); w.destroy()
    print("added:", [s["text"][:40] for s in app.analysis["scenes"] if s["kind"]=="added"])
    app._save_from_review(); go(s4, "All done!")
def s4():
    L=json.load(open(os.environ["LOCALAPPDATA"]+"/CleanListen/learned.json"))
    print("learned cut:", L["cut"]); print("learned kept:", L["kept"]); print("claude_kept:", L["claude_kept"][:3], "| claude_cut:", len(L["claude_cut"]))
    print("csv exists:", os.path.exists(os.environ["LOCALAPPDATA"]+"/CleanListen/claude_findings.csv"))
    app.recheck_same(); app.claude_var.set(False); app.after(600, lambda: (app.start(), go(s5)))
def s5():
    print("re-run learn note:", app.analysis.get("learn_note"))
    print("2nd run:", *state(), sep="\n  ")
    app.share_learned(); app.destroy()
app.after(800, s1); app.after(400000, app.destroy); app.mainloop()
