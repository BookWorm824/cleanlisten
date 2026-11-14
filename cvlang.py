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
LANGS = {"en": "English", "es": "Spanish", "fr": "French", "pt": "Portuguese",
         "ru": "Russian"}

# what a sound track or subtitle track of this language is tagged as inside a video, and how
# a subtitle file next to it is named ("Movie.es.srt", "Movie.spa.srt")
TAGS = {"en": ("eng", "en"),
        "es": ("spa", "es", "esp", "es-es", "es-mx", "es-419", "spanish"),
        "fr": ("fre", "fra", "fr", "fr-fr", "fr-ca", "french"),
        "pt": ("por", "pt", "pob", "pt-br", "pt-pt", "portuguese"),
        "ru": ("rus", "ru", "russian")}
FILE_TAGS = {"en": r"\.(en|eng|english)\b",
             "es": r"\.(es|spa|esp|spanish|español|espanol|castellano|latino)\b",
             "fr": r"\.(fr|fre|fra|french|français|francais|vf|vff|vfq)\b",
             "pt": r"\.(pt|por|pob|ptbr|pt-br|pt-pt|portuguese|portugues|português)\b",
             "ru": r"\.(ru|rus|russian|русский)\b"}
# for the subtitle finder (ISO 639-3)
SUB_LANG = {"en": "eng", "es": "spa", "fr": "fra", "pt": "por", "ru": "rus"}


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
# Auto: working out the language of a video
# ---------------------------------------------------------------------------
# "Auto" on step 1 (the owner, 2026-11-13: "what if the person doesn't know it, would it be
# possible to have an "auto" tab"). The sound track's own label is read first; with none,
# a short sample is listened to with the model for other languages and the language is told
# from its everyday little words. English stays the choice the page starts with: Auto needs
# that model even for a video that turns out to be English.
AUTO = "auto"
CHOICES = {"en": "English", AUTO: "Auto", **{k: v for k, v in LANGS.items() if k != "en"}}


def choice(code):
    """What the drop-down shows for a saved choice: a language, or Auto."""
    return code if code in CHOICES else "en"


def needs_model(code):
    """Whether this choice listens with the model for other languages."""
    return code == AUTO or known(code) != "en"


# languages the listening model hears that CleanView has no word lists for yet, by the
# labels a sound track can carry
OTHER_TAGS = {"ger": "German", "deu": "German", "de": "German", "ita": "Italian",
              "it": "Italian", "dut": "Dutch", "nld": "Dutch", "nl": "Dutch", "pol": "Polish",
              "pl": "Polish", "swe": "Swedish", "sv": "Swedish", "dan": "Danish",
              "nor": "Norwegian", "fin": "Finnish", "ukr": "Ukrainian", "uk": "Ukrainian",
              "jpn": "Japanese", "ja": "Japanese", "kor": "Korean", "ko": "Korean",
              "chi": "Chinese", "zho": "Chinese", "zh": "Chinese", "hin": "Hindi",
              "hi": "Hindi", "ara": "Arabic", "ar": "Arabic", "tur": "Turkish",
              "tr": "Turkish", "gre": "Greek", "ell": "Greek", "heb": "Hebrew",
              "tha": "Thai", "vie": "Vietnamese", "ind": "Indonesian"}


def tag_language(tag):
    """A sound track's language label -> (code, None) for a language CleanView cleans,
    ("other", its name) for one it doesn't, (None, None) for no label or one it can't read."""
    t = (tag or "").strip().lower()
    for code, tags in TAGS.items():
        if t in tags:
            return code, None
    if t in OTHER_TAGS:
        return "other", OTHER_TAGS[t]
    return None, None


# The everyday words of each language. Matched without accents (the listening model often
# leaves them off: "que" for "qué", "tu" for "tú"), and a word only one language has counts
# for more than one several share: Spanish and Portuguese share "que", "por", "tu", "no" and
# "para", and the model's own Spanish sample was taken for Portuguese until they did.
LITTLE_WORDS = {
    "en": "the and you that was for are with his they this have from not but what all were "
          "when your can said there she her him would could about know just don't i'm it's "
          "yeah okay is of to in it he we do me my be on at so no if get got like out up did "
          "how who why here right think want going well ask country",
    "es": "el la los las un una uno y que de en es no sí por para con pero muy está qué él "
          "ella usted ustedes como más esto eso bien aquí yo tú me te se lo le les mi su al "
          "del hay ser fue son estoy estás tengo tiene tienes vamos ahora cuando porque "
          "también nada todo todos gracias señor señora dónde quién cómo nos ya si hacer "
          "puede puedes quiero quieres voy vas va soy eres somos decir dijo sé sabes creo "
          "mira oye bueno vale claro hola adiós entonces siempre nunca allí donde algo mucho "
          "poco menos hombre mujer hijo vez día año ti",
    "fr": "le la les un une et que de des du en est pas ne je tu il elle nous vous ils on ce "
          "ça c'est pour avec mais très où qui quoi oui non mon ma ton son sur dans au aux "
          "plus bien tout fait être avoir j'ai suis était merci comme quand parce alors ici "
          "rien ces cette se y lui votre vos notre faire peut pouvez veux voulez sais savez "
          "dit dire bonjour monsieur madame toujours jamais aussi maintenant chose homme "
          "femme fois jour",
    "pt": "o a os as um uma e que de do da dos das em no na nos nas é não sim por para com "
          "sem mas muito está você vocês ele ela eles elas eu tu me te se meu minha seu sua "
          "nosso como mais isso isto aquilo bem aqui ali tem são foi ser estou tenho tens "
          "vamos agora quando porque também nada tudo todos obrigado obrigada senhor senhora "
          "onde quem já então ao à pelo pela pra tá né fazer pode podes quero queres vou "
          "vais vai sou somos dizer disse sei sabe sabes acho olha bom claro olá tchau "
          "sempre nunca algo pouco menos homem mulher filho vez dia ano coisa gente",
    "de": "der die das und ist nicht ich du er sie es wir ihr ein eine zu den dem mit auf für "
          "von ja nein was wie aber auch so mir mich dich haben habe hat sind war kann nur "
          "noch dann wenn oder hier bitte danke gut sehr mein dein sein alles zwei ende",
    "it": "il lo la i gli le un una e che di è non sì per con ma molto sono sei io tu lui lei "
          "noi voi mi ti si mio mia tuo suo come più questo quello bene qui ho hai ha "
          "abbiamo perché anche niente tutto grazie signore dove chi cosa quando allora "
          "adesso della del nel alla fare può posso voglio vuoi dire detto sempre mai",
}


def _plain(word):
    """A word without its accents, for telling the language by."""
    return "".join(c for c in unicodedata.normalize("NFD", word) if not unicodedata.combining(c))


LITTLE_WORDS = {k: frozenset(_plain(w) for w in v.split()) for k, v in LITTLE_WORDS.items()}
OWN_WORDS = {k: ws - frozenset().union(*(o for j, o in LITTLE_WORDS.items() if j != k))
             for k, ws in LITTLE_WORDS.items()}       # the ones no other language here has
OTHER_HEARD = {"de": "German", "it": "Italian"}
TOO_FEW_WORDS = 15          # fewer than this heard: only a very clear case is told
LITTLE_SHARE = 0.2          # a language's everyday words are at least this much of its talk
CLEAR_SHARE = 0.45          # ... and this much, to tell from just a few words (6 or more)


def which_language(words):
    """The language of some heard (or written) words: (code, None) for one CleanView cleans,
    ("other", its name) for one it doesn't, (None, None) when it can't tell."""
    toks = re.findall(r"[^\W\d_]+(?:'[^\W\d_]+)?", " ".join(str(w) for w in words).lower())
    if len(toks) < 6:
        return None, None
    cyrillic = [t for t in toks if re.search(r"[а-яёіїєґ]", t)]
    if len(cyrillic) >= len(toks) / 2:
        if sum(1 for t in cyrillic if re.search(r"[іїєґ]", t)) > len(cyrillic) / 10:
            return "other", "Ukrainian"
        return "ru", None
    toks = [_plain(t) for t in toks]
    share = {k: sum(1 for t in toks if t in ws) / len(toks) for k, ws in LITTLE_WORDS.items()}
    own = {k: sum(1 for t in toks if t in ws) / len(toks) for k, ws in OWN_WORDS.items()}
    best = max(share, key=lambda k: share[k] + 2 * own[k])
    if share[best] < (LITTLE_SHARE if len(toks) >= TOO_FEW_WORDS else CLEAR_SHARE):
        return None, None
    if best in OTHER_HEARD:
        return "other", OTHER_HEARD[best]
    return best, None


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
NO_ACCENTS = {"es", "fr", "pt"}
# letters written two ways that the lists have one way (Russian ё is usually printed е)
SAME_LETTER = {"ru": {"ё": "е"}}
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
    for a, b in SAME_LETTER.get(lang, {}).items():
        w = w.replace(a, b)
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


# Portuguese, written as norm() leaves the words (no accents: "não" = "nao", "cuzão" =
# "cuzao"; a hyphen joins: "foda-se" = "fodase", "cala-te" = "calate"). Brazil and Portugal.
# Left out on purpose, because the everyday meaning is far more common than the rude one:
# puto (a boy, in Portugal), pau (a stick), pica (stings), rola, bicha (a queue, in Portugal),
# veado (a deer), piranha (the fish), cadela (a female dog), corno (a horn), burro (a donkey),
# besta (a beast), droga (a drug), nossa (our), fogo (fire), bolas (balls), palhaço (a clown).
# Some are still caught in phrases ("que droga", "ora bolas", "nossa senhora").
PT = {
    "strong": [
        r"fod(er|e|es|em|o|a|as|am|ido|ida|idos|idas|endo|eu|eram|ao|oes|ona)", r"fodase",
        r"fodasse", r"caralh(o|os|ada)", r"put(a|as|inha|inhas|aria|arias|eiro|eiros)",
        r"putaquepariu", r"filh[oa]daputa", r"fidaputa", r"bucet(a|as)", r"bocet(a|as)",
        r"xoxot(a|as)", r"xerec(a|as)", r"con(a|as)", r"piroc(a|as)", r"cabr(ao|oes)",
        r"arrombad(o|a|os|as)", r"punhet(a|as|eiro|eiros)",
    ],
    "moderate": [
        r"porras?", r"merd(a|as|inha|inhas)", r"bost(a|as)",
        r"cag(ar|a|as|am|o|ou|ada|adas|ado|ados|ando|ao|oes|ona)",
        r"mij(ar|a|o|ou|ada|ado|ando|ao)", r"cu", r"cuz(ao|oes|ona|onas|inho)",
        r"vagabund(a|as)", r"vadi(a|as)", r"tet(a|as)",
    ],
    "mild": [r"maldit(o|a|os|as)", r"maldicao", r"diabos", r"desgracad(o|a|os|as)",
             r"porcarias?", r"danese"],
    "minced": [r"caramba", r"carambas", r"puxa", r"poxa", r"caraca", r"cacete", r"cacilda",
               r"putz", r"puts", r"orra", r"raios", r"credo", r"diacho"],
    "deity": [r"jesuscristo", r"omg"],
    "samesex": [
        r"gays?", r"homossexua(l|is)", r"homossexualidade", r"lesbic(a|as)", r"bissexua(l|is)",
        r"viad(o|os|inho|inhos)", r"boiolas?", r"baitolas?", r"paneleiros?", r"queers?",
    ],
    "rude": [
        r"estupid(o|a|os|as|ez)", r"idiotas?", r"imbeci(l|s)", r"burrice", r"bob(o|a|os|as)",
        r"tol(o|a|os|as)", r"babacas?", r"otari(o|a|os|as)", r"trouxas?", r"panacas?",
        r"paspalh(o|a|os|as|ao)", r"lerd(o|a|os|as)", r"cretin(o|a|os|as)",
        r"perdedor(a|es|as)?", r"chorao", r"choroes", r"choronas?", r"pirralh(o|a|os|as)",
        r"calaboca", r"calate", r"calese", r"bund(a|as|ao|ona)",
    ],
    "sex": [
        r"sexo", r"sexua(l|is)", r"penis", r"vaginas?", r"orgasmos?", r"masturb[a-z]+",
        r"erecao", r"erecoes", r"ejacul[a-z]+", r"semen", r"esperma", r"camisinhas?",
        r"preservativos?", r"coito", r"porno", r"pornografia", r"prostitut(a|as|o|os)",
        r"tesao", r"transar", r"transou", r"transando",
    ],
}
PT_PHRASES = {
    "mild": [("que", "droga"), ("que", "diabos"), ("com", "os", "diabos"), ("ao", "diabo"),
             ("vai", "pro", "inferno"), ("vai", "para", "o", "inferno"),
             ("va", "para", "o", "inferno"), ("vai", "pro", "diabo"), ("dane", "se"),
             ("que", "se", "dane")],
    "minced": [("puxa", "vida"), ("ora", "bolas"), ("cruz", "credo"), ("credo", "em", "cruz")],
    "deity": [("ai", "meu", "deus"), ("oh", "meu", "deus"), ("meu", "deus", "do", "ceu"),
              ("meu", "deus"), ("deus", "do", "ceu"), ("deus", "meu"), ("por", "deus"),
              ("pelo", "amor", "de", "deus"), ("santo", "deus"),
              ("minha", "nossa", "senhora"), ("nossa", "senhora"), ("virgem", "maria"),
              ("virgem", "santa"), ("jesus", "cristo"), ("ai", "jesus"),
              ("jesus", "maria", "jose"), ("gracas", "a", "deus"), ("deus", "me", "livre"),
              ("deus", "nos", "livre"), ("juro", "por", "deus"), ("sabe", "deus"),
              ("deus", "sabe"), ("valhame", "deus"), ("valha", "me", "deus"),
              ("santa", "mae", "de", "deus"), ("mae", "de", "deus"), ("cristo", "santo"),
              ("deus", "todo", "poderoso")],
    "rude": [("cala", "a", "boca"), ("cale", "a", "boca"), ("calem", "a", "boca"),
             ("cala", "te"), ("fecha", "a", "matraca"), ("te", "odeio"), ("odeio", "voce")],
}
PT_NOT_NEXT = {"raios": {"x", "de", "do", "solares", "gama", "laser", "ultravioleta", "uv"},
               "diabos": {"vermelhos", "e"}}
PT_NOT_BEFORE = {"raios": {"os", "uns", "dois", "tres", "muitos", "com", "seus", "esses",
                           "estes", "de", "por", "varios", "alguns"},
                 "diabos": {"os", "uns", "dois", "tres", "esses", "estes", "pobres", "de"},
                 "credo": {"o", "um", "meu", "seu", "nosso", "do", "no"}}

# Russian, written as norm() leaves the words: small letters, ё as е ("чёрт" = "черт"). Accents
# aren't taken off: й would become и. The swearing is built on a few roots, so most patterns
# take whatever comes after the root.
# Left out on purpose, because the everyday meaning is far more common than the rude one:
# козёл (a goat), свинья (a pig), осёл (a donkey), голубой (light blue), зараза (an
# infection), ёлки (fir trees), черта (a trait; "чёрт" itself and its phrases are in).
RU = {
    "strong": [
        r"ху[йяеию][а-я]*", r"(на|по|до|ни)ху[йяю]", r"[ао]ху[еи][а-я]*",
        r"[а-я]*пизд[а-я]*",
        r"(за|вы|у|на|по|до|разъ|отъ|съ|при|про|объ|подъ|изъ)?еб[аеиоулнсыья][а-я]*",
        r"еб", r"бля", r"бля[дт][а-я]*", r"муда[кч][а-я]*", r"мудил[а-я]*", r"пидор[а-я]*",
        r"пидар[а-я]*", r"пидр[а-я]*",
    ],
    "moderate": [
        r"сук[аиуе]", r"сукой", r"сукам?", r"суч(ка|ки|ку|кой|ара|ий|ья|ье)",
        r"говн[а-я]+", r"говен[а-я]+", r"дерьм[а-я]+",
        r"срать", r"сру", r"срет", r"срешь", r"срал[а-я]*", r"(на|обо|за|по)сра[а-я]+",
        r"срач", r"сран[а-я]+", r"засран[а-я]+", r"ссать", r"ссу", r"ссыт", r"ссал[а-я]*",
        r"(обо|за)сса[а-я]+", r"жоп[а-я]+", r"хер", r"хера", r"херу", r"хером",
        r"херн[а-я]+", r"херов[а-я]*", r"(на|по)хер", r"(ни|до)хера",
        r"сволоч[а-я]+", r"ублюд[а-я]+", r"твар[а-я]+", r"падл[а-я]+", r"мраз[а-я]+",
        r"скотин[а-я]+", r"шлюх[а-я]+", r"траха[а-я]+", r"трахну[а-я]+", r"трахни[а-я]*",
    ],
    "mild": [r"черт", r"чертов[а-я]*", r"чертовски", r"проклят[а-я]+"],
    "minced": [
        r"блин", r"хрен[ьи]?", r"хрена", r"хренов[а-я]*", r"(на|по)хрен", r"(ни|до)хрена",
        r"хренотен[а-я]+", r"фиг(а|у|ом|ня|ни|ню|ней|ово|овый|овая|овое|овые)?",
        r"(на|по)фиг", r"(ни|до)фига", r"офиге[а-я]+", r"офига[а-я]+", r"капец", r"трындец",
        r"пипец", r"звиздец", r"елкипалки", r"емое", r"ешкин", r"екарный", r"едрен[а-я]+",
    ],
    "deity": [r"господи", r"боже"],
    "samesex": [
        r"гей", r"геи", r"гея", r"геев", r"геям", r"геем", r"геями", r"геях",
        r"гомосексуал[а-я]*", r"гомосек[а-я]*", r"гомик[а-я]*", r"лесбиян[а-я]+", r"лесби",
        r"бисексуал[а-я]*", r"педик[а-я]*", r"педераст[а-я]*",
    ],
    "rude": [
        r"дура[кч][а-я]*", r"дура", r"дуры", r"дуру", r"дурой", r"дурень", r"придур[а-я]+",
        r"идиот[а-я]*", r"тупиц[а-я]+", r"туп(ой|ая|ое|ые|ого|ому|ым|ую)", r"кретин[а-я]*",
        r"дебил[а-я]*", r"болван[а-я]*", r"балбес[а-я]*", r"олух[а-я]*", r"гад", r"гады",
        r"гадин[а-я]+", r"заткнись", r"заткнитесь", r"заткни", r"неудачни[кц][а-я]*",
        r"плакс[а-я]+", r"сопля[кч][а-я]*", r"отстой", r"задниц[а-я]+",
    ],
    "sex": [
        r"секс[а-я]*", r"сексуальн[а-я]+", r"пенис[а-я]*", r"вагин[а-я]+", r"оргазм[а-я]*",
        r"мастурб[а-я]+", r"эрекци[а-я]+", r"сперм[а-я]+", r"презерватив[а-я]*", r"порно",
        r"порнограф[а-я]+", r"проститутк[а-я]+",
    ],
}
RU_PHRASES = {
    "moderate": [("твою", "ж", "мать"), ("твою", "мать"), ("мать", "твою")],
    "mild": [("черт", "возьми"), ("черт", "побери"), ("какого", "черта"), ("ни", "черта"),
             ("до", "черта"), ("на", "черта"), ("к", "черту"), ("к", "дьяволу"),
             ("какого", "дьявола")],
    "minced": [("елки", "палки"), ("е", "мое"), ("блин", "горелый")],
    "deity": [("о", "боже", "мой"), ("боже", "мой"), ("о", "боже"), ("господи", "боже"),
              ("господи", "иисусе"), ("ради", "бога"), ("бог", "ты", "мой"),
              ("боже", "правый"), ("матерь", "божья"), ("слава", "богу"),
              ("бог", "его", "знает"), ("бог", "знает"), ("клянусь", "богом"),
              ("не", "дай", "бог"), ("упаси", "бог"), ("упаси", "боже"), ("боже", "упаси"),
              ("иисус", "христос"), ("иисусе", "христе"), ("господи", "помилуй")],
    "rude": [("закрой", "рот"), ("закройте", "рот"), ("закрой", "пасть"),
             ("тебя", "ненавижу"), ("ненавижу", "тебя"), ("ты", "отстой")],
}
# "блин" is also a pancake
RU_NOT_NEXT = {"блин": {"с", "со", "на", "из", "комом"}}
RU_NOT_BEFORE = {"блин": {"один", "этот", "первый", "последний", "вкусный", "горячий",
                          "съел", "съела", "испек", "испекла", "как"}}

WORDS = {code: {k: _c(v) for k, v in lists.items()}
         for code, lists in (("es", ES), ("fr", FR), ("pt", PT), ("ru", RU))}
PHRASES = {"es": ES_PHRASES, "fr": FR_PHRASES, "pt": PT_PHRASES, "ru": RU_PHRASES}
NOT_NEXT = {"es": ES_NOT_NEXT, "fr": FR_NOT_NEXT, "pt": PT_NOT_NEXT, "ru": RU_NOT_NEXT}
NOT_BEFORE = {"es": ES_NOT_BEFORE, "fr": FR_NOT_BEFORE, "pt": PT_NOT_BEFORE,
              "ru": RU_NOT_BEFORE}
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
