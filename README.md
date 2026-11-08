# SCOR 11 dokumendiassistent

Lokaalne rakendus küsimuste esitamiseks **sinu enda** SCOR 11 PDF-dokumendi kohta (eesti või inglise keeles).
Vastused koostatakse ainult dokumendist leitud katkendite põhjal (RAG) ning neil on kontrollitavad viited kujul
`[1] failinimi.pdf, PDF lk 42` koos originaalkatkendiga.

* Kõik töötab sinu arvutis: Streamlit kuulab ainult `127.0.0.1`, keelemudel ja embedding-mudel töötavad kohalikus
  [Ollamas](https://github.com/ollama/ollama). Pilve-API-sid, telemeetriat ega väliseid veebifonte ei kasutata.
* Pärast Pythoni sõltuvuste ja Ollama mudelite paigaldamist töötab rakendus ilma internetita.
* Repositoorium **ei sisalda** SCOR 11 dokumenti. Lisa PDF, mille kasutamise õigus sul on.

> **NB!** See repo sisaldas varem Railway veebirakenduse juhiseid (`CLAUDE.md`). See rakendus on teadlikult
> lokaalne ega ole mõeldud Railway'sse paigaldamiseks: dokumendi sisu ei tohi lahkuda arvutist.

---

## 1. Arhitektuur

| Moodul | Ülesanne |
|---|---|
| `app.py` | Streamliti kasutajaliides (eesti keeles) |
| `scor_assistant/pdf_processing.py` | PDF-i kontroll (laiend, suurus, `%PDF-` päis, parool), SHA-256, teksti eraldamine lehekülgede kaupa (PyMuPDF), tabelid, OCR-vajaduse tuvastus, leheküljevaate renderdamine |
| `scor_assistant/chunking.py` | Lõikudeks jagamine (~650 tokenit, 15% kattuvus), lõik ei ületa kunagi lehekülje piiri |
| `scor_assistant/storage.py` | SQLite (dokumendid, leheküljed, lõigud, indeksi olek) + NumPy `.npy` vektorifailid |
| `scor_assistant/ollama_client.py` | Kohalik Ollama HTTP-klient (`/api/tags`, `/api/embed`, `/api/chat`) |
| `scor_assistant/indexing.py` | Indekseerimine ja indeksi kehtivuse kontroll (failiräsi + embedding-mudel + seaded) |
| `scor_assistant/search.py` | Hübriidotsing: koosinussarnasus + BM25 märksõnaotsing koodide täpse vastega, RRF-ühendamine, duplikaatide eemaldamine |
| `scor_assistant/answering.py` | Süsteemijuhis, konteksti piiramine, järelküsimuste täpsustamine, viidete programmiline kontroll |
| `scor_assistant/pipeline.py` | Küsimuse töövoog: täpsustamine → uus otsing → vastus |

Kasutatud meetodid:
* **BM25** märksõnaotsing (Robertson & Zaragoza, 2009, *The Probabilistic Relevance Framework: BM25 and Beyond*,
  Foundations and Trends in IR 3(4)), parameetrid k1 = 1,5, b = 0,75.
* **Reciprocal Rank Fusion** tulemuste ühendamiseks (Cormack, Clarke & Büttcher, 2009, SIGIR '09), k = 60.
* Protsessikoodid (nt kujul `sP1.1`, `RL.1.1`, `BP.012`) ja lühendid (nt `OFCT`) tuvastatakse küsimusest ning
  nende **täpne** esinemine lõigus tõstab lõigu tulemuste tippu (`XQ1.2` ei sobitu `XQ1.21`-ga).

Otsingu järjestusnumbrid **ei ole** vastuse õigsuse tõenäosus ja neid ei näidata protsendina.

---

## 2. Paigaldamine (Windows)

### 2.1 Python

1. Laadi alla Python **3.12 või 3.13** (64-bitine) aadressilt <https://www.python.org/downloads/windows/>.
2. Paigaldamisel märgi **„Add python.exe to PATH”**.
3. Kontrolli PowerShellis:

```powershell
py -3 --version
```

> Sõltuvuste versioonid (`requirements.txt`) on testitud Python 3.13-ga Linuxis. Kasutatud NumPy ja PyMuPDF
> versioonidel on olemas Windowsi (win_amd64) paketid Python 3.12 jaoks (kontrollitud `pip download` abil).

### 2.2 Ollama

1. Laadi alla ja paigalda Ollama Windowsi versioon: <https://ollama.com/download/windows>.
2. Ollama käivitub taustal ja kuulab vaikimisi aadressil `http://127.0.0.1:11434`.
3. Kontrolli:

```powershell
ollama --version
```

### 2.3 Mudelite allalaadimine (vajab ühekordselt internetti)

Vaja on **kahte** mudelit: keelemudel vastuste koostamiseks ja **mitmekeelne** embedding-mudel otsinguks.

```powershell
ollama pull bge-m3
```

```powershell
ollama pull qwen2.5:7b
```

Paigaldatud mudelid ja nende kettamaht:

```powershell
ollama list
```

Rakenduse külgpaneel näitab kõiki paigaldatud mudeleid; keelemudeli ja embedding-mudeli saab valida eraldi.

### 2.4 Virtuaalkeskkond ja sõltuvused

Käivitusskript teeb selle esimesel käivitusel ise. Käsitsi:

```powershell
py -3 -m venv .venv
```

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

Testide jaoks (valikuline):

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
```

### 2.5 Seadistus (valikuline)

```powershell
Copy-Item config.example.env .env
```

Muuda `.env` failis nt vaikemudeleid (`SCOR_LLM_MODEL`, `SCOR_EMBED_MODEL`), Ollama aadressi (`SCOR_OLLAMA_URL`),
PDF-i suuruspiirangut (`SCOR_MAX_UPLOAD_MB`), lõigu pikkust ja kattuvust, katkendite arvu (`SCOR_TOP_K`) ning
kontekstiakent (`SCOR_NUM_CTX`). Ollama aadress peab olema lokaalne (`localhost`, `127.0.0.1`, `::1`);
mittelokaalne aadress lükatakse tagasi, kui `SCOR_ALLOW_REMOTE_OLLAMA=true` pole teadlikult seatud.
Kui tõstad `SCOR_MAX_UPLOAD_MB` üle 100, tõsta ka `.streamlit/config.toml` failis `maxUploadSize`.

---

## 3. Käivitamine Windowsis

Projektikaustas:

```powershell
powershell -ExecutionPolicy Bypass -File .\start.ps1
```

Skript loob vajadusel `.venv`-i ja paigaldab sõltuvused, kontrollib Ollama olemasolu ning avab rakenduse
aadressil <http://localhost:8501>. Sõltuvuste uuesti paigaldamiseks lisa `-Install`. Peatamiseks vajuta `Ctrl+C`.

Ilma skriptita:

```powershell
.\.venv\Scripts\python.exe -m streamlit run app.py --server.address 127.0.0.1
```

---

## 4. PDF-i lisamine ja esimene indeks

1. Külgpaneelil **„Laadi üles SCOR 11 PDF”** → vali fail.
   Rakendus kontrollib laiendit, suurust ja PDF-i päist, arvutab SHA-256 räsi ja eraldab teksti lehekülgede kaupa
   (edenemisriba). Seejärel näidatakse lehekülgede arvu, tekstiga lehekülgede arvu ning hoiatusi
   (tekstita leheküljed, tabelid).
2. Vali **Keelemudel** ja **Embedding-mudel**.
3. Vajuta **„Indekseeri dokument”**. Indekseerimine loob iga lõigu jaoks embedding-vektori (edenemisriba).
   Suure dokumendi puhul võib see CPU-l võtta mitu minutit.
4. Esita küsimus või vali näidisküsimus. Vastuse all on **Viited** ja avatav **„Allikad”** osa
   originaalkatkenditega. Lüliti **„Näita PDF lk X”** näitab PDF-i lehekülge (katkendi algus esile tõstetud).
   Kogu PDF-i saab avada nupuga **„Ava / laadi alla PDF”** või **„Ava PDF arvuti PDF-vaaturis”**.

Märkused:
* **„PDF lk X”** on PDF-faili lehekülg (1 = faili esimene lehekülg), mis võib erineda dokumendile trükitud numbrist.
* **Skannitud PDF**: kui masinloetavat teksti ei leita, dokumenti ei indekseerita ja kuvatakse OCR-i juhis
  (nt [OCRmyPDF](https://ocrmypdf.readthedocs.io/): `ocrmypdf --language eng sisend.pdf valjund.pdf`).
* **Tabelid** eraldatakse ridadena `lahter | lahter` ja märgistatakse `[Tabel] … [/Tabel]`. Keeruliste tabelite
  (liidetud lahtrid, mitmetasandilised päised) eraldus võib olla ebatäpne – võrdle leheküljevaatega.
* **Jaotise pealkiri** võetakse PDF-i sisukorrast/järjehoidjatest; kui neid pole, siis selgelt suurema fondiga
  lühikestest ridadest. Kui usaldusväärset pealkirja ei leita, jäetakse väli tühjaks.
* Taaskäivitamisel indeksit uuesti ei looda. Indeks muutub kehtetuks (ja rakendus palub uuesti indekseerida),
  kui muutub PDF-faili räsi, embedding-mudel või töötlemisseaded (lõigu pikkus, kattuvus, tabelite eraldus,
  töötlemise versioon).
* Järelküsimuste puhul kasutatakse eelnevat vestlust ainult küsimuse täpsustamiseks; iga küsimuse jaoks tehakse
  uus dokumendiotsing. Varasemaid vastuseid allikana ei kasutata.
* Vastuse viiteid kontrollitakse programmiliselt: olematud viited (nt `[12]`, kui allikaid oli 8) eemaldatakse ja
  sellest antakse hoiatus. Leheküljenumbrid ja failinimed võetakse andmebaasist, mitte mudeli tekstist.

---

## 5. Kohalikud andmed

Kõik andmed on kaustas `data\` (muudetav: `SCOR_DATA_DIR`), mis on Gitist välistatud:

| Asukoht | Sisu |
|---|---|
| `data\scor_assistant.sqlite3` | dokumendid, leheküljetekst, lõigud, indeksi olek, viimased mudelivalikud |
| `data\documents\<sha256>.pdf` | üles laaditud PDF-i koopia |
| `data\vectors\<sha256>_<seadete räsi>.npy` | embedding-vektorid |

Kustutamine:
* ühe dokumendi kõik andmed: külgpaneel → **„Kustuta dokument ja indeks”** → **„Jah, kustuta”**;
* kõik andmed (rakendus peab olema peatatud):

```powershell
Remove-Item -Recurse -Force .\data\documents, .\data\vectors, .\data\scor_assistant.sqlite3
```

Vestlusajalugu hoitakse ainult brauseri seansi mälus ja see kaob lehe sulgemisel või nupuga **„Tühjenda vestlus”**.
Ollama mudeleid saab kustutada käsuga `ollama rm <mudel>`.

---

## 6. Mudeli valik: kiirus, mälu ja kvaliteet

Allolevad soovitused on **insenerihinnangud**, mitte selle rakendusega mõõdetud tulemused. Tegelikku eesti keele
vastuste kvaliteeti tuleb kontrollida oma dokumendiga (vt jaotis 8).

**Embedding-mudel** (otsing):
* Soovitus: `bge-m3`. Mudel on loodud mitmekeelseks otsinguks (autorite järgi üle 100 keele, sisend kuni 8192
  tokenit; Chen jt, 2024, *BGE M3-Embedding*, arXiv:2402.03216). See võimaldab eestikeelse küsimusega leida
  ingliskeelset teksti. Ainult ingliskeelsed mudelid (nt `nomic-embed-text`, `all-minilm`) toimivad eestikeelsete
  küsimustega eeldatavasti halvemini.
* Embedding-mudeli vahetamisel tuleb dokument uuesti indekseerida (rakendus tuvastab selle automaatselt).

**Keelemudel** (vastused):
* Suurem mudel (rohkem parameetreid) järgib reegleid ja eesti keelt üldiselt paremini, kuid on aeglasem ja vajab
  rohkem RAM-i/VRAM-i. Kvantiseeritud mudeli mälutarve on ligikaudu võrdne selle kettamahuga (`ollama list`)
  pluss kontekstiakna (KV-vahemälu) osa, mis kasvab koos `SCOR_NUM_CTX` väärtusega.
* Rusikareegel (hinnang, kontrolli oma arvutis):
  * ~3–4 mld parameetrit (nt `qwen2.5:3b`, `gemma3:4b`): töötab ka 8 GB RAM-iga, kiire, nõrgem eesti keel ja
    reeglite järgimine;
  * ~7–8 mld (nt `qwen2.5:7b`, `llama3.1:8b`): soovituslik algus, vajab umbes 8–16 GB vaba mälu;
  * ~14 mld ja rohkem: parem kvaliteet, vajab 16+ GB ja on ilma GPU-ta aeglane.
* Ilma GPU-ta võib vastuse koostamine võtta kümneid sekundeid kuni minuteid. Aegumise korral suurenda
  `SCOR_REQUEST_TIMEOUT` või vali väiksem mudel.
* `SCOR_NUM_CTX` (vaikimisi 8192) piirab, mitu katkendit mudelile antakse. Väiksem väärtus vähendab mälutarvet,
  kuid ka konteksti. Väärtus ei tohi ületada mudeli toetatud kontekstipikkust.

---

## 7. Testid

```powershell
.\.venv\Scripts\python.exe -m pytest -q
```

Testid kasutavad **sünteetilist, selgelt märgistatud testdokumenti** (`tests/conftest.py`, tekst
„SÜNTEETILINE TESTDOKUMENT – EI OLE SCOR 11 SISU”, väljamõeldud koodid `XQ1.2`, `QZR.7` jne) ning
deterministlikku võlts-embeddingut ja võlts-Ollama serverit (`tests/fake_ollama.py`, ainult `127.0.0.1`).
Need kontrollivad tehnilist toimimist, **mitte** päris mudeli vastuste kvaliteeti. Kaetud on:

* PDF-i leheküljenumbrite säilimine ja lõikude piirdumine ühe leheküljega;
* indeksi salvestamine ja korduskasutamine pärast „taaskäivitust”;
* indeksi kehtetuks muutumine embedding-mudeli või seadete muutmisel ning PDF-faili muutmisel;
* protsessikoodi täpne leidmine (`XQ1.2` vs `XQ1.21`) ja lühendi leidmine;
* olematu allikaviite tagasilükkamine ja viidete sidumine failinime/leheküljega;
* tühja, pildipõhise (skannitud) ja vigase PDF-i käsitlemine; tühja dokumendi mitteindekseerimine;
* tabeliteksti ja koodide säilimine; Ollama aadressi lokaalsuse kontroll; prompt-injection siltide neutraliseerimine;
* kasutajaliidese käivitumine ilma Ollamata ning küsimus-vastus-viited-kustutamine voog (Streamlit AppTest).

## 8. Kvaliteedikontroll tegeliku dokumendiga (teha ise)

Pärast oma SCOR 11 PDF-i indekseerimist kontrolli näiteks:
1. Kas näidisküsimustele antud viidete „PDF lk X” leheküljed sisaldavad tõesti väidetud infot?
2. Kas protsessikoodiga küsimus (nt dokumendis esinev kood) leiab õige jaotise?
3. Kas dokumendis puuduvale teemale vastatakse „Dokumendist ei leitud sellele küsimusele piisavat vastust”?
4. Kas tabelitest pärit katkendid on loetavad?

## 9. Veaolukorrad

| Teade | Lahendus |
|---|---|
| „Ollamaga ei saa ühendust” | Käivita Ollama (Start-menüü → Ollama) või `ollama serve` |
| „Mudelit … ei ole Ollamas paigaldatud” | `ollama pull <mudel>` |
| „… ei vastanud … sekundi jooksul” | Oota mudeli laadimist, vali väiksem mudel või suurenda `SCOR_REQUEST_TIMEOUT` |
| „PDF-ist ei õnnestunud masinloetavat teksti eraldada” | Tee PDF-ile OCR ja laadi uuesti üles |
| „PDF on parooliga kaitstud” | Eemalda parool |
| „Indeks on aegunud” | Vajuta „Indekseeri dokument” |
