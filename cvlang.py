"""Other languages (1.18.80; the owner, 2026-11-13: "is it possible to add additional language
capabilities ... like if i wanted to scan a movie in spanish", then "i would do the easier
group of languages": Spanish, French, Portuguese and Russian, Spanish first).

English is untouched: it keeps its own listening model and its own word lists in cvcore.py.
Picking another language on step 1 changes three things:

- The listening model. One model hears about 25 European languages (NeMo Parakeet TDT 0.6B
  v3, the sister of the English one). It is downloaded once, the first time another language
  is picked (about 490 MB), so people who only clean English never get it.
- The word lists. Each language has its own, in the same groups as the English ones
  (swearing, mild, God's name, minced oaths, same-sex words, rude words kids copy).
  cvcore's norm(), find_language(), listed_word() and mask() hand over to this file when
  cvcore.LANG isn't "en".
- Subtitles and the sound track are looked for in that language.

This file must not import cvcore (cvcore imports it)."""
import os
import re
import shutil
import tarfile
import tempfile
import unicodedata
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent

# code -> name, in the order the start page shows them
LANGS = {"en": "English", "es": "Spanish", "fr": "French"}

# what a sound track or subtitle track of this language is tagged as inside a video, and how
# a subtitle file next to it is named ("Movie.es.srt", "Movie.spa.srt")
TAGS = {"en": ("eng", "en"),
        "es": ("spa", "es", "esp", "es-es", "es-mx", "es-419", "spanish"),
        "fr": ("fre", "fra", "fr", "fr-fr", "fr-ca", "french")}
FILE_TAGS = {"en": r"\.(en|eng|english)\b",
             "es": r"\.(es|spa|esp|spanish|español|espanol|castellano|latino)\b",
             "fr": r"\.(fr|fre|fra|french|français|francais|vf|vff|vfq)\b"}
SUB_LANG = {"en": "eng", "es": "spa", "fr": "fra"}   # for the subtitle finder (ISO 639-3)


# the language being cleaned now. One video's worker process cleans one language, and the
# window sets it for the review it has open (cvcore.use_language).
LANG = "en"


def known(code):
    return code if code in LANGS else "en"


def use(code):
    global LANG
    LANG = known(code)
    return LANG


def name(code):
    return LANGS[known(code)]


def reader_note(code):
    """A sentence for the AI that reads the dialogue, so it knows what it is reading."""
    if known(code) == "en":
        return ""
    return (f" The dialogue is in {name(code)}. Judge every line by what it means in "
            f"{name(code)}, and when you quote words copy them exactly as they are written, "
            f"in {name(code)}, never translated.")


# ---------------------------------------------------------------------------
# The listening model for other languages
# ---------------------------------------------------------------------------
MODEL_NAME = "sherpa-onnx-nemo-parakeet-tdt-0.6b-v3-int8"
MODEL_URL = ("https://github.com/k2-fsa/sherpa-onnx/releases/download/asr-models/"
             f"{MODEL_NAME}.tar.bz2")
MODEL_FILES = ("encoder.int8.onnx", "decoder.int8.onnx", "joiner.int8.onnx", "tokens.txt")
MODEL_MB = 490                       # the download, for the progress message
MODEL_WHAT = "the listening model for other languages"


def model_dir():
    """Where the model is kept (CLEANVIEW_MULTI_MODEL: another folder, for the tests)."""
    return Path(os.environ.get("CLEANVIEW_MULTI_MODEL") or HERE / "models" / MODEL_NAME)


def model_ready():
    d = model_dir()
    return all((d / f).is_file() and (d / f).stat().st_size > 0 for f in MODEL_FILES)


def install_model(progress=None, url=None):
    """Download and unpack the model (one time). Only its four files are kept; they are put
    in place at the end, so a download that stops halfway leaves nothing half-done."""
    say = progress or (lambda f, m: None)
    d = model_dir()
    d.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(suffix=".tar.bz2", dir=d.parent)
    os.close(fd)
    part = d.with_name(d.name + ".part")
    try:
        say(0.0, f"Getting {MODEL_WHAT} (one time, about {MODEL_MB} MB)…")
        try:
            with urllib.request.urlopen(url or MODEL_URL, timeout=60) as r, open(tmp, "wb") as f:
                total = int(r.headers.get("Content-Length") or 0) or MODEL_MB << 20
                got = 0
                while True:
                    block = r.read(1 << 20)
                    if not block:
                        break
                    f.write(block)
                    got += len(block)
                    say(0.9 * min(1.0, got / total),
                        f"Getting {MODEL_WHAT} (one time): {got >> 20} of {total >> 20} MB…")
        except OSError as ex:
            raise RuntimeError(f"Couldn't download {MODEL_WHAT}. Check your internet "
                               f"connection and try again.\n\n{ex}") from ex
        say(0.92, "Unpacking the listening model…")
        shutil.rmtree(part, ignore_errors=True)
        part.mkdir(parents=True)
        try:
            with tarfile.open(tmp, "r:bz2") as tf:
                for m in tf:
                    base = Path(m.name).name
                    if base in MODEL_FILES and m.isfile():
                        with tf.extractfile(m) as src, open(part / base, "wb") as dst:
                            shutil.copyfileobj(src, dst)
        except (tarfile.TarError, EOFError, OSError) as ex:
            raise RuntimeError(f"The download of {MODEL_WHAT} looked wrong. Try again."
                               f"\n\n{ex}") from ex
        if not all((part / f).is_file() and (part / f).stat().st_size for f in MODEL_FILES):
            raise RuntimeError(f"The download of {MODEL_WHAT} looked wrong. Try again.")
        d.mkdir(parents=True, exist_ok=True)
        for f in MODEL_FILES:
            os.replace(part / f, d / f)
        say(1.0, "The listening model is ready.")
    finally:
        try:
            os.remove(tmp)
        except OSError:
            pass
        shutil.rmtree(part, ignore_errors=True)


# ---------------------------------------------------------------------------
# Words
# ---------------------------------------------------------------------------
# accents are taken off before matching ("cabrón" = "cabron", "cállate" = "callate"), because
# subtitles and speech recognition often leave them out. Spanish ñ stays: "año" is a year.
NO_ACCENTS = {"es", "fr"}
# French joins short words on with an apostrophe ("l'idiot", "t'es", "qu'il", "j'm'en"): they
# come off, so the word after them is the one matched
ELIDED = {"fr": re.compile(r"^(?:[cdjlmnst]|qu|jusqu|lorsqu|puisqu|quelqu)'")}


def norm(w, lang="es"):
    """A word as the lists have it: small letters, no punctuation, no accents (ñ kept)."""
    w = unicodedata.normalize("NFC", str(w)).lower().replace("’", "'").replace("‘", "'")
    if lang in NO_ACCENTS:
        w = w.replace("ñ", "\0")
        w = "".join(c for c in unicodedata.normalize("NFD", w) if not unicodedata.combining(c))
        w = w.replace("\0", "ñ")
    w = re.sub(r"[^\w']|_", "", w)
    if lang in ELIDED:
        while ELIDED[lang].match(w):
            w = ELIDED[lang].sub("", w, count=1)
    return w.strip("'")


def mask(word):
    """'mierda' -> 'm*****' (any alphabet)."""
    core = "".join(c for c in word if c.isalpha())
    return word if len(core) <= 1 else core[0] + "*" * (len(core) - 1)


def _c(pats):
    return [re.compile(p + r"$") for p in pats]


# Spanish, written as norm() leaves the words (no accents). Spain and Latin America both.
# Left out on purpose, because the everyday meaning is far more common than the rude one:
# concha (shell), perra (a female dog), coger (to take), huevos (eggs), capullo (a cocoon),
# tortillera (a tortilla maker), infierno (hell, the place), Jesús (a very common name).
# They are still caught inside the phrases below ("hijo de perra", "la concha de tu madre").
ES = {
    "strong": [
        r"jod[a-zñ]+",                                   # joder, jodido, jódete, jodiendo
        r"foll(ar|a|as|an|ando|ada|adas|ado|ados|amos|e|es|en|o|aba|aban|aron|arte|arme|arse|"
        r"arla|arlo|arnos|emos|on|ones)",                # (not folleto, follaje)
        r"ching[a-zñ]+",                                 # chingar, chingada, chingón
        r"put(a|o|as|os|ita|itas|ito|itos|on|ona|ones|onas|ada|adas|azo|ero|eros|ear|eada|"
        r"eando|isimo|isima|icos?)", r"reput[ao]s?", r"putamadre",
        r"hij(o|a|ue)put(a|as)", r"hideputa", r"j(ue|o)puta", r"hijueputas?",
        r"coñ(o|os|azo|azos)", r"verg(a|as|azo|azos|on|ona|ones)",     # (not vergüenza)
        r"poll(a|as|on|ones)", r"cabron(a|es|as|cito|azo)?", r"encabron[a-zñ]+",
        r"conchetumadre", r"conchesumadre", r"culia(o|os|do|dos|da|das)", r"qliao",
        r"cule(ar|ando|ada|ado)", r"culi(ar|ando)", r"mamaguevos?", r"mamahuevos?",
        r"malparid(o|a|os|as)", r"soplapollas", r"comemierdas?", r"careverga", r"carepicha",
    ],
    "moderate": [
        r"mierd(a|as|ero|eros|oso|osa|osos|osas|ita|ecilla)",
        r"cag(ar|a|as|an|o|ue|ues|uen|ada|adas|ado|ados|ando|on|ona|ones|aste|aron|arla|"
        r"arse|arme|arte|alera)",
        r"me(ar|ando|ada|adas|ado|ados|arse|arme|arte|on|ona|ones)",
        r"pendej(o|a|os|as|ada|adas|ear|ez)", r"culer(o|a|os|as)", r"ojetes?",
        r"cul(o|os|ito|itos|azo|on|ona|ones)", r"lameculos", r"tet(a|as|ona|onas|azas)",
        r"gilipollas", r"gilipoll(ez|eces)", r"gilis?", r"carajos?", r"pinches?",
        r"cojon(es|udo|uda|udos|udas|azos)?", r"acojon[a-zñ]+", r"tocapelotas",
        r"hostias?", r"ostias?", r"puñet(a|as|ero|era|eros|eras)", r"zorr(a|as|on|ona)",
        r"mamon(a|es|as)?", r"mamad(a|as)", r"huevon(a|es|as)?", r"guevon(a|es|as)?",
        r"we+on(a|es|as)?", r"wevon(a|es|as)?", r"bolud(o|a|os|as|ez|eces)",
        r"pelotud(o|a|os|as|ez|eces)", r"cojud(o|a|os|as|ez)", r"pirob(o|a|os|as)",
        r"chuch(a|as)", r"cabre(ado|ada|ados|adas)",
    ],
    "mild": [
        r"maldit(o|a|os|as)", r"maldicion", r"malditasea", r"diablos", r"condenad(o|a|os|as)",
    ],
    "minced": [
        r"caray", r"carambas?", r"jolin(es)?", r"jope", r"jobar", r"ostras", r"mecachis",
        r"cachis", r"recorcholis", r"corcholis", r"caspita", r"rayos", r"diantres?",
        r"pucha", r"puchica", r"chuta", r"hijole", r"pardiez", r"leñe", r"gilipuertas",
    ],
    "deity": [r"jesucristo", r"omg"],
    "samesex": [
        r"gays?", r"homosexual(es)?", r"homosexualidad", r"lesbian(a|as|o|ismo)",
        r"bisexual(es)?", r"maricon(es|a|as|azo|ada|adas)?", r"maric(a|as)", r"jot(o|os)",
        r"boller(a|as)", r"queers?",
    ],
    "rude": [
        r"estupid(o|a|os|as|ez|eces)", r"idiotas?", r"imbecil(es)?", r"tont(o|a|os|as)",
        r"bob(o|a|os|as)", r"mens(o|a|os|as)", r"babos(o|a|os|as)", r"tarad(o|a|os|as)",
        r"zopenc(o|a|os|as)", r"cretin(o|a|os|as)", r"zoquetes?", r"perdedor(a|es|as)?",
        r"mocos(o|a|os|as)", r"lloron(es)?", r"sons(o|a|os|as)", r"zonz(o|a|os|as)",
        r"pazguat(o|a)", r"majader(o|a|os|as)", r"papanatas", r"lel(o|a|os|as)",
        r"mequetrefes?", r"callate", r"callense", r"callaos", r"apestas",
    ],
    # sex words an AI may mute on its own (as cvcore's explicit list is for English)
    "sex": [
        r"sexo", r"sexual(es)?", r"penes?", r"vaginas?", r"orgasmos?", r"masturb[a-zñ]+",
        r"ereccion(es)?", r"eyacul[a-zñ]+", r"semen", r"condon(es)?", r"preservativos?",
        r"coito", r"porno", r"pornografia", r"prostitut(a|as|o|os)", r"rameras?",
        r"fornic[a-zñ]+",
    ],
}
ES_PHRASES = {
    "strong": [("hijo", "de", "perra"), ("hija", "de", "perra"), ("hijos", "de", "perra"),
               ("la", "concha", "de", "tu", "madre"), ("la", "concha", "de", "su", "madre"),
               ("concha", "de", "tu", "madre"), ("concha", "tu", "madre")],
    "mild": [("maldita", "sea"), ("que", "diablos"), ("que", "demonios"), ("como", "diablos"),
             ("como", "demonios"), ("donde", "diablos"), ("donde", "demonios"),
             ("quien", "diablos"), ("quien", "demonios"), ("al", "diablo"),
             ("mil", "demonios"), ("vete", "al", "infierno"), ("vayase", "al", "infierno"),
             ("vayanse", "al", "infierno"), ("al", "infierno", "con")],
    "deity": [("ay", "dios", "mio"), ("oh", "dios", "mio"), ("dios", "mio"), ("ay", "dios"),
              ("oh", "dios"), ("por", "dios", "santo"), ("por", "dios"), ("dios", "santo"),
              ("santo", "dios"), ("valgame", "dios"), ("por", "el", "amor", "de", "dios"),
              ("por", "amor", "de", "dios"), ("santa", "madre", "de", "dios"),
              ("madre", "de", "dios"), ("gracias", "a", "dios"), ("sabe", "dios"),
              ("dios", "sabe"), ("juro", "por", "dios"), ("dios", "me", "libre"),
              ("dios", "nos", "libre"), ("dios", "no", "lo", "quiera"), ("dios", "bendito"),
              ("bendito", "dios"), ("dios", "todopoderoso"), ("virgen", "santa"),
              ("virgen", "santisima"), ("jesus", "maria", "y", "jose"), ("ay", "jesus"),
              ("jesus", "cristo"), ("por", "cristo"), ("cristo", "santo"), ("santo", "cristo"),
              ("ay", "diosito"), ("diosito", "santo")],
    "rude": [("cierra", "la", "boca"), ("cierren", "la", "boca"), ("cierra", "el", "pico"),
             ("cierra", "el", "hocico"), ("te", "odio"), ("cabeza", "hueca"),
             ("cabeza", "de", "chorlito")],
}
# words that are only a swear some of the time: left alone before or after these
ES_NOT_NEXT = {"rayos": {"x", "de", "del", "solares", "gamma", "laser", "ultravioleta", "uv",
                         "cosmicos", "infrarrojos"},
               "ostras": {"frescas", "con", "y", "de", "al", "crudas", "fritas"},
               "diablos": {"rojos", "azules", "y"}}
ES_NOT_BEFORE = {"rayos": {"los", "unos", "dos", "tres", "muchos", "con", "sus", "esos",
                           "estos", "de", "por", "varios", "algunos"},
                 "ostras": {"las", "unas", "de", "con", "comer", "comiendo", "comimos", "docena"},
                 "diablos": {"los", "unos", "dos", "tres", "esos", "estos", "pobres", "de"},
                 "hostia": {"sagrada", "santa", "consagrada"},
                 "hostias": {"sagradas", "santas", "consagradas"},
                 }


# French, written as norm() leaves the words: no accents ("enculé" = "encule", "ça" = "ca")
# and without the short words joined on with an apostrophe ("l'idiot" = "idiot", "j'm'en
# fous" = "en fous", "nom d'un chien" = "nom un chien"). France and Quebec both.
# Left out on purpose, because the everyday meaning is far more common than the rude one:
# baiser (a kiss), chatte (a female cat), queue (a tail), fou/fous (crazy), mince (thin),
# punaise (a thumbtack), purée (mash), flûte (a flute), la vache (the cow), la ferme (the
# farm), tapette (a fly swatter), calvaire (an ordeal), andouille (a sausage), sacré (sacred).
# Some are still caught in phrases ("oh mince", "ferme-la", "oh la vache").
FR = {
    "strong": [
        r"put(e|es|ain|ains|asse|asses)", r"encul(e|es|ee|ees|er|ait|ant|ons|ez|eur|eurs|ade)",
        r"niqu(e|es|er|ent|ez|ons|ait|ais)", r"bais(e|es|ent|ait|ais|ant|ee|ees|ez|ons)",
        r"foutre", r"bites?", r"teub", r"salop(e|es|ard|ards|erie|eries)", r"salauds?",
        r"enfoire(s|e|es)?", r"conn(ard|ards|asse|asses)", r"batard(e|s|es)?",
        r"pouff?iasses?", r"petasses?", r"trouducs?",
        r"branl(er|e|es|ent|eur|eurs|euse|euses|ette|ettes|ee|ait)",
        r"tabarna[kc]", r"cali(ss|sse|ce)", r"cri(ss|sse)", r"(o|e)sti(e)?", r"sacrament",
        r"ciboire", r"viarge",
    ],
    "moderate": [
        r"merd(e|es|ier|ique|iques|eux|euse|er|ait|ouille)",
        r"emmerd(e|es|er|ent|eur|eurs|euse|ant|ante|ants|antes|ement|ements|ez|ait|ais)",
        r"demerd(e|er|ez|es|ent)",
        r"chi(er|e|es|ent|ant|ante|ants|antes|ait|ais|ottes|asse|eur|eurs|erie|eries)",
        r"culs?", r"cons?", r"conn(e|es)", r"conneries?",
        r"deconn(e|er|es|ez|ait|ais|ent)", r"couill(e|es|on|ons|onne|onner|onnade|u|us)",
        r"piss(e|er|es|ent|ait|eux|euse|ou)", r"foutu(e|s|es)?", r"foutez", r"foutaises?",
        r"foutoir", r"garces?", r"nichons?", r"ducon",
    ],
    "mild": [r"bordel", r"maudit(e|s|es)?", r"damne(e|s|es)?"],
    "minced": [
        r"zut", r"sapristi", r"saperlipopette", r"sacrebleu", r"morbleu", r"parbleu",
        r"palsambleu", r"ventrebleu", r"diantre", r"fichtre", r"bigre", r"mazette",
        r"scrogneugneu", r"tabarnouche", r"tabarouette", r"mautadit", r"mautadine", r"torrieu",
    ],
    "deity": [r"jesuschrist", r"omg"],
    "samesex": [
        r"gays?", r"homosexuel(s|le|les)?", r"homosexualite", r"lesbiennes?",
        r"bisexuel(s|le|les)?", r"homos?", r"pd", r"pedes?", r"tarlouzes?", r"tantouzes?",
        r"gouines?", r"goudous?", r"queers?",
    ],
    "rude": [
        r"idiot(e|s|es)?", r"imbeciles?", r"stupides?", r"debiles?", r"abruti(e|s|es)?",
        r"cretin(e|s|es)?", r"na[sz]es?", r"nigaud(e|s|es)?", r"benets?", r"minables?",
        r"tocard(e|s|es)?", r"bouffon(s|ne|nes)?", r"ploucs?", r"morveux", r"morveuses?",
        r"pleurnichard(e|s|es)?", r"pleurnicheu(r|se|rs|ses)", r"mauviettes?", r"chochottes?",
        r"taistoi", r"taisezvous", r"fermela",
    ],
    "sex": [
        r"sexes?", r"sexuel(s|le|les)?", r"penis", r"vagins?", r"orgasmes?", r"masturb[a-z]+",
        r"erections?", r"ejacul[a-z]+", r"sperme", r"preservatifs?", r"coit", r"pornos?",
        r"pornographie", r"prostituee?s?", r"forniqu[a-z]+", r"fornication",
    ],
}
FR_PHRASES = {
    "moderate": [("en", "fous"), ("en", "fout"), ("me", "fous"), ("te", "fous"), ("se", "fout"),
                 ("fous", "le", "camp"), ("fous", "moi")],
    "mild": [("au", "diable"), ("que", "diable"), ("va", "au", "diable"),
             ("allez", "au", "diable"), ("va", "en", "enfer"), ("allez", "en", "enfer")],
    "minced": [("oh", "mince"), ("ah", "mince"), ("mince", "alors"), ("oh", "punaise"),
               ("oh", "puree"), ("oh", "flute"), ("flute", "alors"), ("bon", "sang"),
               ("nom", "un", "chien"), ("nom", "une", "pipe"), ("oh", "la", "vache"),
               ("ah", "la", "vache"), ("juste", "ciel")],
    "deity": [("oh", "mon", "dieu"), ("ah", "mon", "dieu"), ("mon", "dieu"), ("bon", "dieu"),
              ("nom", "de", "dieu"), ("dieu", "du", "ciel"), ("grand", "dieu"),
              ("grands", "dieux"), ("doux", "jesus"), ("jesus", "marie", "joseph"),
              ("jesus", "christ"), ("seigneur", "dieu"), ("oh", "seigneur"), ("ah", "seigneur"),
              ("doux", "seigneur"), ("dieu", "merci"), ("par", "dieu"),
              ("pour", "amour", "de", "dieu"), ("dieu", "seul", "sait"), ("dieu", "sait"),
              ("jure", "devant", "dieu"), ("dieu", "me", "garde"), ("dieu", "nous", "garde"),
              ("dieu", "ne", "plaise"), ("sainte", "vierge"), ("sainte", "mere", "de", "dieu"),
              ("mere", "de", "dieu"), ("dieu", "tout", "puissant"), ("bonte", "divine")],
    "rude": [("tais", "toi"), ("taisez", "vous"), ("ferme", "la"), ("ferme", "ta", "gueule"),
             ("ta", "gueule"), ("vos", "gueules"), ("ferme", "ta", "bouche"),
             ("ferme", "ton", "clapet"), ("boucle", "la"), ("je", "te", "deteste"),
             ("tu", "crains"), ("tu", "pues"), ("ca", "craint"), ("est", "nul"),
             ("poule", "mouillee")],
}
FR_NOT_NEXT = {"con": {"carne", "brio"}, "cul": {"sec"},
               "homo": {"sapiens", "erectus", "habilis"}, "bouffon": {"du"}}
FR_NOT_BEFORE = {"nique": {"pique"}, "batard": {"pain"}, "branle": {"en"}}

WORDS = {"es": {k: _c(v) for k, v in ES.items()}, "fr": {k: _c(v) for k, v in FR.items()}}
PHRASES = {"es": ES_PHRASES, "fr": FR_PHRASES}
NOT_NEXT = {"es": ES_NOT_NEXT, "fr": FR_NOT_NEXT}
NOT_BEFORE = {"es": ES_NOT_BEFORE, "fr": FR_NOT_BEFORE}
ORDER = ("strong", "moderate", "deity", "samesex", "mild", "minced", "rude")


def _innocent(words, i, lang):
    w = words[i]
    nxt = words[i + 1] if i + 1 < len(words) else ""
    prev = words[i - 1] if i else ""
    return (nxt in NOT_NEXT[lang].get(w, ()) or prev in NOT_BEFORE[lang].get(w, ()))


def find_language(words, cats, mine=(), lang="es"):
    """Like cvcore.find_language, for another language: (i, j, category) spans of words[i:j]
    to mute. words: already through norm(). mine: her own words and phrases, always muted."""
    lists, cats = WORDS[lang], set(cats)
    phrases = sorted(((p, c) for c in ORDER if c in cats for p in PHRASES[lang].get(c, ())),
                     key=lambda pc: -len(pc[0]))
    mine = sorted(set(mine), key=len, reverse=True)
    hits, n, i = [], len(words), 0
    while i < n:
        ph = next((p for p in mine if tuple(words[i:i + len(p)]) == p), None)
        if ph:
            hits.append((i, i + len(ph), "mine"))
            i += len(ph)
            continue
        got = next(((p, c) for p, c in phrases if tuple(words[i:i + len(p)]) == p), None)
        if got:
            hits.append((i, i + len(got[0]), got[1]))
            i += len(got[0])
            continue
        w = words[i]
        cat = next((c for c in ORDER if c in cats and any(p.match(w) for p in lists[c])), None)
        if cat and not _innocent(words, i, lang):
            hits.append((i, i + 1, cat))
        i += 1
    return hits


def listed_word(word, mine=(), cats=None, lang="es"):
    """True if a word or phrase is on this language's lists (cats: only those lists; None:
    every one), so an AI can't mute a misheard name on its own."""
    on = set(ORDER) if cats is None else set(cats)
    parts = [p for p in (norm(t, lang) for t in re.split(r"[\s\-]+", word)) if p]
    for ph in list(mine) + [p for c in on for p in PHRASES[lang].get(c, ())]:
        if any(tuple(parts[k:k + len(ph)]) == tuple(ph) for k in range(len(parts) - len(ph) + 1)):
            return True
    lists = WORDS[lang]
    return any(p.match(w) for w in parts
               for c in list(on) + ["sex"] for p in lists.get(c, ()))
