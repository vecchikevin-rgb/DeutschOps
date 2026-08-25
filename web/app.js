/* DeutschOps — frontend.
 *
 * Vanilla, nessun framework, nessun build step, nessuna richiesta esterna:
 * l'app deve funzionare col Wi-Fi spento. Lo stato vive qui, la verita' vive
 * sul server.
 *
 * LINGUA: l'interfaccia parla inglese, il contenuto e' tedesco. Non e' una
 * preferenza estetica — grammar_db ed error_db portano gia' le spiegazioni in
 * `explanation_en`, quindi l'inglese e' dove il materiale sta. Il codice e i
 * commenti restano in italiano, come nel resto del progetto.
 */

'use strict';

// ------------------------------------------------------------------ zone

const ZONE = [
  { id: 'home',      nome: 'Home',      icona: 'i-home',      pronta: true  },
  { id: 'reading',   nome: 'Reading',   icona: 'i-reading',   pronta: true  },
  { id: 'practice',  nome: 'Practice',  icona: 'i-practice',  pronta: true  },
  { id: 'listening', nome: 'Listening', icona: 'i-listening', pronta: true  },
  { id: 'kursbuch',  nome: 'Kursbuch',  icona: 'i-book',      pronta: true  },
  { id: 'reference', nome: 'Reference', icona: 'i-reference', pronta: true  },
  { id: 'exam',      nome: 'Exam',      icona: 'i-exam',      pronta: true  },
  { id: 'progress',  nome: 'Progress',  icona: 'i-progress',  pronta: true  },
];

const stato = {
  zona: 'home',
  durata: 15,          // minuti scelti all'apertura: 5 / 15 / 30
  briefing: null,
  sessione: null,      // sessione di lettura in corso
  pratica: null,       // sessione di allenamento in corso
  progressi: null,     // i numeri della zona Progress
  anki: null,          // il riquadro Anki, che arriva dopo
  livello: null,       // banda CEFR scelta per l'allenamento, null = tutte
  esame: null,         // il quadro B2
  scrittura: null,     // prova di scrittura in corso
  registraMs: false,   // il modulo per registrare un Modellsatz
  kursbuch: null,      // { lektioni, aperta } della zona Kursbuch
  kursbuchDettaglio: null,   // il dettaglio della Lektion aperta
  kursbuchDettaglioNumero: null,  // quale Lektion e' aperta nel dettaglio —
                                   // separato da kursbuch.aperta perche' si puo'
                                   // arrivare al dettaglio anche da fuori la zona
                                   // Kursbuch (es. il puntatore in Exam), dove
                                   // stato.kursbuch e' ancora null
  ascolto: null,       // sessione di ascolto in corso
};

// ------------------------------------------------------------------ utilita'

const $ = (sel) => document.querySelector(sel);

function el(tag, attr = {}, ...figli) {
  const n = document.createElement(tag);
  for (const [k, v] of Object.entries(attr)) {
    if (v === null || v === undefined || v === false) continue;
    if (k === 'class') n.className = v;
    else if (k === 'html') n.innerHTML = v;
    else if (k.startsWith('on')) n.addEventListener(k.slice(2).toLowerCase(), v);
    else n.setAttribute(k, v === true ? '' : v);
  }
  for (const f of figli.flat()) {
    if (f === null || f === undefined || f === false) continue;
    n.append(f.nodeType ? f : document.createTextNode(String(f)));
  }
  return n;
}

function icona(id) {
  const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
  const use = document.createElementNS('http://www.w3.org/2000/svg', 'use');
  use.setAttribute('href', '#' + id);
  svg.append(use);
  svg.setAttribute('aria-hidden', 'true');
  return svg;
}

async function api(percorso, opzioni) {
  const r = await fetch(percorso, opzioni);
  if (!r.ok) throw new Error(`${r.status} ${r.statusText}`);
  return r.json();
}

function fraseConParola(testo, parola) {
  // Evidenzia la parola nuova nella frase, senza toccare il resto.
  const re = new RegExp(`\\b(${parola.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')}\\w*)`, 'i');
  const frag = document.createDocumentFragment();
  const m = testo.match(re);
  if (!m) { frag.append(testo); return frag; }
  const i = testo.indexOf(m[0]);
  frag.append(testo.slice(0, i));
  frag.append(el('mark', {}, m[0]));
  frag.append(testo.slice(i + m[0].length));
  return frag;
}

// ------------------------------------------------------------------ nav

function disegnaZone() {
  const nav = $('#zone');
  nav.replaceChildren(...ZONE.map((z) =>
    el('button', {
      class: 'zona',
      disabled: !z.pronta,
      title: z.pronta ? z.nome : `${z.nome} — coming in ${z.fase}`,
      'aria-current': stato.zona === z.id ? 'page' : null,
      onclick: () => vai(z.id),
    }, icona(z.icona), z.nome)
  ));
}

function vai(id) {
  stato.zona = id;
  location.hash = id;
  disegnaZone();
  if (stato.briefing) disegnaPie();
  disegna();
}

// ------------------------------------------------------------------ home

function disegnaHome() {
  const b = stato.briefing;
  const c = $('#contenuto');

  const durate = [5, 15, 30].map((m) =>
    el('button', {
      class: 'secondario',
      'aria-pressed': stato.durata === m ? 'true' : 'false',
      onclick: () => { stato.durata = m; disegna(); },
    }, `${m} min`)
  );

  // La banda CEFR vale solo per l'allenamento: la lettura pesca dal corpus,
  // dove il livello non è dichiarato. Cambiarla butta la sessione in corso,
  // perché mescolare A2 e B2 nella stessa sessione è esattamente ciò che il
  // selettore serve a evitare.
  const bande = el('div', { class: 'durata', style: 'margin-top:var(--s3)' },
    el('span', { class: 'durata-etichetta' }, 'Practice level'),
    el('button', {
      class: 'secondario',
      'aria-pressed': stato.livello === null ? 'true' : 'false',
      onclick: () => { stato.livello = null; stato.pratica = null; disegna(); },
    }, 'Any'),
    ...BANDE.map((b) =>
      el('button', {
        class: 'secondario',
        'aria-pressed': stato.livello === b ? 'true' : 'false',
        onclick: () => { stato.livello = b; stato.pratica = null; disegna(); },
      }, b)));

  c.replaceChildren(
    el('section', { class: 'suggerimento' },
      el('h1', {}, b.titolo),
      el('p', {}, b.motivo),
      el('div', { class: 'durata' },
        el('span', { class: 'durata-etichetta' }, 'Session length'),
        ...durate,
        el('button', {
          class: 'primario',
          style: 'margin-left:auto',
          onclick: () => vai(b.zona_consigliata || 'reading'),
        }, b.azione || 'Start')
      ),
      bande
    ),
    el('dl', { class: 'cifre' },
      ...b.cifre.map((k) =>
        el('div', { class: 'cifra' },
          el('dt', {}, k.etichetta),
          el('dd', {}, String(k.valore), k.nota ? el('small', {}, ' ' + k.nota) : null)
        )
      )
    ),
    b.avvisi.length
      ? el('section', {},
          el('h2', { style: 'font-size:1rem;margin:0 0 var(--s3)' }, 'Needs attention'),
          ...b.avvisi.map((a) =>
            el('div', { class: 'riga' },
              el('div', { class: 'riga-capo' }, el('strong', {}, a.titolo)),
              el('div', { class: 'provenienza' }, a.dettaglio))
          ))
      : null
  );
}

// ------------------------------------------------------------------ reading

/* Il ciclo e' quello di Anki, e l'ordine conta: prima ti esponi, poi scopri,
 * poi valuti. Chiedere "la sai?" PRIMA di mostrare la risposta misura la tua
 * fiducia, non la tua conoscenza — e le due divergono proprio sulle parole che
 * credi di sapere. Il voto arriva solo dopo lo scoprimento. */
const VOTI = [
  { n: 1, id: 'again', nome: 'Again',  nota: 'never seen it' },
  { n: 2, id: 'hard',  nome: 'Hard',   nota: 'came back slowly' },
  { n: 3, id: 'good',  nome: 'Good',   nota: 'knew it' },
  { n: 4, id: 'easy',  nome: 'Easy',   nota: 'instant' },
];

async function avviaLettura() {
  const quante = { 5: 6, 15: 15, 30: 30 }[stato.durata];
  const d = await api(`/api/frasi?n=${quante}`);
  stato.sessione = {
    frasi: d.frasi,
    i: 0,
    fase: 'domanda',   // domanda -> risposta -> (avanti) ... -> fine
    scelta: null,      // quale opzione ha preso, null se ha saltato
    avviata: Date.now(),
  };
}

const LETTERE = ['A', 'B', 'C', 'D'];

function disegnaLettura() {
  const c = $('#contenuto');
  const s = stato.sessione;

  if (!s) {
    c.replaceChildren(el('p', { class: 'vuoto' }, 'Preparing sentences…'));
    avviaLettura().then(disegna).catch(mostraErrore);
    return;
  }

  if (s.fase === 'fine') return disegnaFineLettura();

  const f = s.frasi[s.i];
  if (!f) { s.fase = 'fine'; return disegna(); }

  const tot = s.frasi.length;
  const intestazione = [
    el('div', { class: 'avanzamento' },
      el('span', {}, `${s.i + 1} of ${tot}`),
      el('span', {}, `from ${f.lezione}`)),
    el('div', { class: 'barra' }, el('i', { style: `width:${(s.i / tot) * 100}%` })),
  ];

  if (s.fase === 'risposta') return disegnaRisposta(c, intestazione, f);

  // --- domanda: la frase col buco e le quattro alternative. -----------
  // I distrattori vengono dal tuo corpus e condividono il suffisso con la
  // parola giusta, quindi si discriminano solo dal contesto.
  c.replaceChildren(
    ...intestazione,
    el('article', { class: 'esercizio' },
      el('p', { class: 'stimolo' }, f.buco),
      f.opzioni && f.opzioni.length
        ? el('div', { class: 'opzioni' },
            ...f.opzioni.map((o, i) =>
              el('button', { class: 'opzione', onclick: () => scopri(o) },
                el('span', { class: 'opzione-tasto' }, LETTERE[i]),
                el('span', { class: 'de opzione-parola' }, o))))
        : el('p', { class: 'provenienza' },
            'Not enough similar words for multiple choice on this one.')),
    el('div', { class: 'durata' },
      el('button', { class: 'secondario', onclick: () => scopri(null) },
        "I don't know ", el('kbd', {}, 'Space')))
  );
}

function scopri(scelta) {
  const s = stato.sessione;
  s.scelta = scelta;
  s.fase = 'risposta';
  disegna();
}

function disegnaRisposta(c, intestazione, f) {
  const s = stato.sessione;
  const indovinata = s.scelta !== null && s.scelta === f.nuova;

  c.replaceChildren(
    ...intestazione,
    el('article', { class: 'esercizio' },
      el('p', { class: 'stimolo' }, fraseConParola(f.testo, f.nuova)),

      // L'esito della scelta, solo se ha scelto.
      s.scelta !== null
        ? el('div', { class: 'esito ' + (indovinata ? 'ok' : 'no') },
            el('div', { class: 'esito-capo' },
              el('span', { class: 'esito-segno' }, indovinata ? '✓' : '✗'),
              indovinata ? f.nuova : `${f.nuova} — you picked “${s.scelta}”`))
        : null,

      el('p', { class: 'provenienza', style: 'margin-top:var(--s4)' },
        `Appears ${f.frequenza}× across your lessons`),

      // Solo qui, DOPO la risposta: prima rivelerebbe la parola che il
      // multiple choice deve far indovinare (qui la risposta E' il
      // significato, a differenza degli esercizi di grammatica dove la
      // traduzione non tocca la forma). Vedi traduzione() sotto.
      traduzione(f),

      // Gli altri contesti reali: come Stefanie la usa davvero.
      f.contesti && f.contesti.length
        ? el('div', { class: 'contesti' },
            el('h3', {}, 'Elsewhere in your lessons'),
            ...f.contesti.map((x) =>
              el('div', { class: 'riga' },
                el('div', { class: 'de', style: 'font-size:1.0625rem' },
                  fraseConParola(x.testo, f.nuova)),
                el('div', { class: 'provenienza' }, x.lezione))))
        : null
    ),

    el('div', { class: 'voti' },
      ...VOTI.map((v) =>
        el('button', {
          class: 'voto ' + v.id,
          onclick: () => vota(v.n),
        },
          el('span', { class: 'voto-tasto' }, String(v.n)),
          el('span', { class: 'voto-nome' }, v.nome),
          el('span', { class: 'voto-nota' }, v.nota)))
    ),

    // Il quinto tasto non e' un voto: e' il canale per dire che la FRASE non
    // va. `completabile()` filtra su regole sintattiche e prende il grosso, ma
    // la deducibilita' dipende dal significato — e li' l'unico giudice sei tu.
    el('div', { class: 'segnala' },
      el('button', { class: 'segnala-tasto', onclick: () => segnalaFrase(f) },
        el('span', { class: 'voto-tasto' }, '5'),
        "Something's off — don't show this again"))
  );
}

function segnalaFrase(f) {
  api('/api/segnala', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      testo: f.testo,
      parola: f.nuova,
      lezione: f.lezione,
      opzioni: f.opzioni || [],
      fonte: f.fonte || 'lezione',
    }),
  }).catch(() => { /* segnalare non deve mai interrompere la sessione */ });

  const s = stato.sessione;
  f.segnalata = true;
  f.voto = null;                 // segnalata non e' votata: non entra nelle misure
  s.i += 1;
  s.scelta = null;
  s.fase = s.i >= s.frasi.length ? 'fine' : 'domanda';
  disegna();
}

function vota(n) {
  const s = stato.sessione;
  const f = s.frasi[s.i];

  f.voto = n;
  f.scelta = s.scelta;
  f.indovinata = s.scelta !== null && s.scelta === f.nuova;

  s.i += 1;
  s.scelta = null;
  s.fase = s.i >= s.frasi.length ? 'fine' : 'domanda';
  disegna();
}

async function disegnaFineLettura() {
  const s = stato.sessione;
  const c = $('#contenuto');

  const votate = s.frasi.filter((f) => f.voto);
  const segnalate = s.frasi.filter((f) => f.segnalata);
  const conta = (n) => votate.filter((f) => f.voto === n).length;
  const deboli = votate.filter((f) => f.voto <= 2);
  const scelte = votate.filter((f) => f.scelta);

  if (!s.registrata) {
    s.registrata = true;
    api('/api/sessione', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        zona: 'reading',
        durata_scelta: stato.durata,
        secondi: Math.round((Date.now() - s.avviata) / 1000),
        viste: votate.length,
        voti: { again: conta(1), hard: conta(2), good: conta(3), easy: conta(4) },
        // Il dettaglio serve piu' dell'aggregato: da qui escono le carte da
        // aggiungere in Anki e le parole su cui tornare.
        parole: votate.map((f) => ({
          parola: f.nuova,
          voto: f.voto,
          frequenza: f.frequenza,
          lezione: f.lezione,
          scelta: f.scelta,
          indovinata: f.indovinata,
        })),
      }),
    }).catch(() => { /* il registro non deve mai bloccare la sessione */ });
  }

  const riga = (f) =>
    el('div', { class: 'riga' },
      el('div', { class: 'riga-capo' },
        el('span', { class: 'de', style: 'font-size:1.125rem' }, f.nuova),
        el('span', { class: 'conteggio' }, `${f.frequenza}×`),
        el('span', { class: 'provenienza' },
          VOTI.find((v) => v.n === f.voto)?.nome,
          f.scelta && !f.indovinata ? ` · you picked “${f.scelta}”` : '')),
      el('div', { class: 'de', style: 'font-size:1rem;color:var(--matita)' }, f.testo));

  c.replaceChildren(
    el('section', { class: 'suggerimento' },
      el('h1', {}, 'Session done'),
      el('p', {}, `${votate.length} sentences`
                + (scelte.length
                    ? ` · ${scelte.filter((f) => f.indovinata).length}/${scelte.length} picked correctly`
                    : '')
                + (segnalate.length
                    ? ` · ${segnalate.length} flagged, won't come back`
                    : '')),
      el('div', { class: 'riepilogo-voti' },
        ...VOTI.map((v) =>
          el('div', { class: 'voto-conteggio ' + v.id },
            el('strong', {}, String(conta(v.n))),
            el('span', {}, v.nome)))),
      el('div', { class: 'durata', style: 'margin-top:var(--s5)' },
        el('button', {
          class: 'primario',
          onclick: () => { stato.sessione = null; disegna(); },
        }, 'Another round'),
        el('button', { class: 'secondario', onclick: () => vai('home') }, 'Home'))),

    deboli.length
      ? el('section', {},
          el('h2', { style: 'font-size:1rem;margin:0 0 var(--s3)' },
            'Worth another look'),
          ...deboli.map(riga))
      : null,

    votate.length > deboli.length
      ? el('details', { style: 'margin-top:var(--s5)' },
          el('summary', { class: 'provenienza' },
            `The other ${votate.length - deboli.length}`),
          ...votate.filter((f) => f.voto > 2).map(riga))
      : null
  );
}

// ------------------------------------------------------------------ practice

/* La zona di produzione. Qui si SCRIVE, e non e' una svista rispetto alla
 * lettura, dove si sceglie fra quattro opzioni.
 *
 * In lettura la parola e' nuova per definizione: scegliere misura se il
 * contesto basta a riconoscerla, ed e' la misura giusta. Qui la parola non e'
 * nuova — e' una regola che hai gia' sbagliato davanti a Stefanie. Riconoscerla
 * fra quattro alternative e' facile e da' l'illusione di saperla; scriverla e'
 * quello che serve a parlare, ed e' quello che l'esame misura.
 *
 * L'attrito di digitare in tedesco esiste, ed e' reale su tastiera italiana.
 * Si compensa dove si puo': barra umlaut, Invio che manda, e una valutazione
 * che accetta «aus der schweiz» segnalando l'ortografia invece di bocciarla. */

const QUANTI = { 5: 5, 15: 10, 30: 20 };
const BANDE = ['A1', 'A2', 'B1', 'B2'];

async function avviaPratica() {
  const l = stato.livello ? `&livello=${stato.livello}` : '';
  const d = await api(`/api/esercizi?n=${QUANTI[stato.durata]}${l}`);
  stato.pratica = {
    perLivello: d.per_livello || {},
    esercizi: d.esercizi || [],
    i: 0,
    fase: 'domanda',
    aiuto: 0,          // gradino raggiunto su QUESTO esercizio
    risposta: '',
    esito: null,
    inCorso: false,    // una valutazione in volo
    avviso: d.avviso || null,
    generati: d.generati || 0,
    costo: d.costo_eur || 0,
    avviata: Date.now(),
  };
}

function disegnaPratica() {
  const c = $('#contenuto');
  const p = stato.pratica;

  if (!p) {
    // La prima apertura puo' dover generare il deposito: e' una chiamata LLM e
    // ci mette una decina di secondi. Dirlo e' meglio che far girare una
    // rotella — un'attesa spiegata non e' un'attesa sospetta.
    c.replaceChildren(
      el('p', { class: 'vuoto' },
        'Building exercises from your own corrections…',
        el('br'), el('small', {}, 'Only when the pool runs low. A few seconds.'))
    );
    avviaPratica().then(disegna).catch(mostraErrore);
    return;
  }

  if (p.fase === 'fine') return disegnaFinePratica();

  const e = p.esercizi[p.i];
  if (!e) {
    if (!p.esercizi.length) return disegnaPraticaVuota(c, p);
    p.fase = 'fine';
    return disegna();
  }

  const tot = p.esercizi.length;
  const intestazione = [
    el('div', { class: 'avanzamento' },
      el('span', {},
        `${p.i + 1} of ${tot}`,
        // Il livello sta accanto al conteggio, non sull'esercizio: dice a che
        // altezza stai lavorando, ed e' un'informazione sulla sessione.
        e.livello ? el('span', { class: 'livello' }, e.livello) : null),
      el('span', {}, e.motivo || e.categoria || '')),
    el('div', { class: 'barra' }, el('i', { style: `width:${(p.i / tot) * 100}%` })),
  ];

  if (p.fase === 'esito') return disegnaEsito(c, intestazione, e);

  // --- domanda ---------------------------------------------------------
  const campo = el('input', {
    class: 'campo', type: 'text', autocomplete: 'off', spellcheck: 'false',
    lang: 'de', value: p.risposta,
    placeholder: 'your answer in German',
    oninput: (ev) => { p.risposta = ev.target.value; },
    onkeydown: (ev) => {
      if (ev.key === 'Enter') { ev.preventDefault(); inviaRisposta(); }
    },
  });

  const aperti = (e.scala || []).filter((g) => g.grado <= p.aiuto);
  const prossimo = (e.scala || []).find((g) => g.grado === p.aiuto + 1);

  c.replaceChildren(
    ...intestazione,
    el('article', { class: 'esercizio' },
      el('p', { class: 'consegna' }, e.consegna),
      el('p', { class: 'stimolo' }, e.stimolo),
      traduzione(e),
      glossa(e),

      ...aperti.map(disegnaGradino),

      campo,
      barraUmlaut(campo),
      el('div', { class: 'risposta-riga' },
        el('button', { class: 'primario', onclick: () => inviaRisposta() },
          p.inCorso ? 'Checking…' : 'Check ', p.inCorso ? '' : el('kbd', {}, '⏎'))),

      el('div', { class: 'scala' },
        el('span', { class: 'scala-etichetta' },
          p.aiuto ? `Help used: ${p.aiuto} of 3` : 'Stuck?'),
        prossimo
          ? el('button', {
              class: 'gradino-tasto', disabled: p.inCorso,
              onclick: () => { p.aiuto = prossimo.grado; disegna(); },
            }, el('span', { class: 'n' }, String(prossimo.grado)), prossimo.nome)
          : el('span', { class: 'provenienza' }, 'No more hints.'),
        el('button', {
          class: 'gradino-tasto resa-tasto', disabled: p.inCorso,
          onclick: () => arrenditi(),
        }, 'Show the answer')),

      // La segnalazione sta anche QUI, non solo dopo la risposta: il momento in
      // cui ti accorgi che un esercizio non e' risolvibile e' mentre lo guardi,
      // non dopo esserti arreso. Segnalarlo prima di rispondere non lascia
      // nessun errore nel quaderno.
      el('div', { class: 'segnala' },
        el('button', {
          class: 'segnala-tasto', disabled: p.inCorso,
          onclick: () => segnalaEsercizio(e),
        }, el('span', { class: 'voto-tasto' }, '5'),
           "Can't be worked out — drop this one"))
    )
  );

  campo.focus();
  campo.setSelectionRange(campo.value.length, campo.value.length);
}

/* La traduzione dell'intera frase, come se il buco fosse già riempito.
 *
 * Non regala la risposta: quello che devi produrre è la FORMA tedesca — caso,
 * desinenza, posizione, ausiliare — e una traduzione inglese non la esprime.
 * «The customers keep discussing the price» non dice se è der Preis o den Preis,
 * ed è esattamente quello il punto dell'esercizio.
 *
 * Quello che regala è il contesto, e senza contesto non c'è esercizio difficile:
 * c'è un muro davanti a cui ci si ferma. Ed è la riga che resta utile dopo,
 * quando la frase si rilegge per impararla e non per risolverla. */
function traduzione(e) {
  if (!e.traduzione) return null;
  return el('p', { class: 'traduzione' }, e.traduzione);
}

/* La glossa: l'inglese di ESATTAMENTE quello che va nel buco.
 *
 * Non è un aiuto e non è il primo gradino della scala — è ciò che rende
 * l'esercizio una domanda invece di un indovinello. «Meine Firma hat eine neue
 * Fabrik ___ gebaut» ammette im Norden, im Süden, in Berlin, letztes Jahr:
 * niente nella frase decide quale. Con «in the north» accanto, l'unica cosa
 * che resta da sapere è la forma tedesca — in + dem → im + Dativ — che è
 * l'unica cosa che l'esercizio voleva misurare.
 *
 * Regala il SIGNIFICATO di proposito. Quello che si allena è la FORMA. */
function glossa(e) {
  if (!e.gloss) return null;
  return el('p', { class: 'glossa' },
    el('span', { class: 'glossa-buco' }, '___'),
    el('span', { class: 'glossa-uguale' }, '='),
    e.gloss);
}

function disegnaGradino(g) {
  return el('div', { class: 'gradino' },
    el('div', { class: 'gradino-capo' }, `${g.grado} · ${g.nome}`),
    el('p', { class: g.grado === 3 ? 'struttura' : null }, g.testo));
}

function inviaRisposta(gradoResa) {
  const p = stato.pratica;
  if (p.inCorso) return;
  const e = p.esercizi[p.i];
  const aiuto = gradoResa === undefined ? p.aiuto : gradoResa;

  p.inCorso = true;
  disegna();

  api('/api/risposta', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ id: e.id, risposta: p.risposta, aiuto }),
  }).then((esito) => {
    p.inCorso = false;
    if (esito.errore) return mostraErrore(new Error(esito.errore));
    p.esito = esito;
    p.fase = 'esito';
    // L'esito si attacca all'esercizio: a fine sessione serve tutto insieme.
    e.risolto = esito.risolto;
    e.corretta = esito.corretta;
    e.aiuto = aiuto;
    e.scritto = p.risposta;
    e.costo = esito.costo_eur || 0;
    disegna();
  }).catch((err) => { p.inCorso = false; mostraErrore(err); });
}

function arrenditi() {
  // Il quarto gradino non e' un aiuto piu' grande: e' una resa, e passa dalla
  // stessa strada di una risposta — perche' il seguito e' lo stesso, quaderno
  // compreso.
  stato.pratica.aiuto = 4;
  inviaRisposta(4);
}

function disegnaEsito(c, intestazione, e) {
  const p = stato.pratica;
  const x = p.esito;
  const s = x.storico || {};
  const ok = x.risolto;

  const righeStorico = [];
  if (s.volte_regola > 1) {
    righeStorico.push(`${ordinale(s.volte_regola)} time on this rule`);
  }
  if (s.volte_categoria > 1) {
    righeStorico.push(`${s.volte_categoria}× on ${s.categoria} overall`);
  }
  const provenienza = [];
  if (s.in_lezione) provenienza.push(`${s.in_lezione} with Stefanie`);
  if (s.nell_app) provenienza.push(`${s.nell_app} here`);

  c.replaceChildren(
    ...intestazione,
    el('article', { class: 'esercizio' },
      el('p', { class: 'consegna' }, e.consegna),
      el('p', { class: 'stimolo' }, e.stimolo),
      traduzione(e),
      glossa(e),

      el('div', { class: 'esito ' + (ok ? 'ok' : 'no') },
        el('div', { class: 'esito-capo' },
          el('span', { class: 'esito-segno' }, ok ? '✓' : '✗'),
          x.cosa || (ok ? 'Correct.' : 'Not right.')),

        el('div', { class: 'de forma' }, x.forma_corretta),
        !ok && e.scritto
          ? el('div', { class: 'scritto' }, 'you wrote ', el('s', {}, e.scritto))
          : null,

        x.perche ? el('p', { class: 'regola' }, x.perche) : null,

        righeStorico.length
          ? el('div', { class: 'recidiva' },
              righeStorico.join(' · '),
              provenienza.length ? ` — ${provenienza.join(', ')}` : '',
              s.prima && s.prima !== s.ultima
                ? el('div', {}, `first ${s.prima}, last ${s.ultima}`)
                : null)
          : null,

        x.aiuto
          ? el('div', { class: 'recidiva' },
              x.aiuto >= 4
                ? 'You asked for the answer — this one counts as unsolved.'
                : `Solved at help step ${x.aiuto}. It comes back.`)
          : null),

      el('div', { class: 'risposta-riga' },
        el('button', { class: 'primario', onclick: () => avantiPratica() },
          p.i + 1 >= p.esercizi.length ? 'Finish ' : 'Next ', el('kbd', {}, '⏎')),
        // Verso la consultazione come RICERCA, non come collegamento: i nomi
        // delle regole nel quaderno sono testo libero, e affermare una
        // corrispondenza qui sarebbe lo stesso errore corretto in F2.
        e.regola
          ? el('button', { class: 'secondario', onclick: () => vaiACercare(e.regola) },
              'Look it up')
          : null,
        x.giudicata_da === 'modello'
          ? el('span', { class: 'provenienza' },
              `judged by the model · ${(x.costo_eur || 0).toFixed(4)} €`)
          : el('span', { class: 'provenienza' }, 'checked offline · free')),

      // Segnalare DOPO la risposta ritira anche l'errore appena scritto nel
      // quaderno: una risposta sbagliata a una domanda indovinabile non dice
      // niente su cosa sai, e falserebbe il profilo d'errore.
      el('div', { class: 'segnala' },
        el('button', { class: 'segnala-tasto', onclick: () => segnalaEsercizio(e) },
          el('span', { class: 'voto-tasto' }, '5'),
          'Bad exercise — drop it and undo the record'))
    )
  );
}

function segnalaEsercizio(e) {
  api('/api/segnala', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      tipo: 'esercizio',
      testo: e.stimolo,
      consegna: e.consegna,
      gloss: e.gloss || '',
      regola: e.regola,
      categoria: e.categoria,
      id: e.id,
    }),
  }).catch(() => { /* segnalare non deve mai interrompere la sessione */ });

  // Esce dal conteggio: non e' ne' risolto ne' sbagliato — non e' successo.
  const p = stato.pratica;
  e.segnalato = true;
  delete e.aiuto;
  delete e.risolto;
  p.i += 1;
  p.aiuto = 0;
  p.risposta = '';
  p.esito = null;
  p.fase = p.i >= p.esercizi.length ? 'fine' : 'domanda';
  disegna();
}

function ordinale(n) {
  const resto = n % 100;
  if (resto >= 11 && resto <= 13) return `${n}th`;
  return n + ({ 1: 'st', 2: 'nd', 3: 'rd' }[n % 10] || 'th');
}

function avantiPratica() {
  const p = stato.pratica;
  p.i += 1;
  p.aiuto = 0;
  p.risposta = '';
  p.esito = null;
  p.fase = p.i >= p.esercizi.length ? 'fine' : 'domanda';
  disegna();
}

function disegnaPraticaVuota(c, p) {
  const conte = p.perLivello || {};
  const altrove = Object.entries(conte).filter(([l]) => l !== stato.livello);
  c.replaceChildren(
    el('section', { class: 'suggerimento' },
      el('h1', {}, stato.livello ? `Nothing left at ${stato.livello}` : 'Nothing to drill'),
      el('p', {}, p.avviso
        ? `The exercise pool could not be refilled. ${p.avviso}`
        : stato.livello
          ? 'Every exercise at this level is done or closed.'
          : 'Every rule in the notebook is either closed or already queued. '
            + 'Process a lesson to feed it more.'),
      // Dire «vuoto» senza dire dove sono gli altri è un vicolo cieco.
      altrove.length
        ? el('div', { class: 'durata' },
            el('span', { class: 'durata-etichetta' }, 'Still available'),
            ...altrove.map(([l, n]) =>
              el('button', {
                class: 'secondario',
                onclick: () => { stato.livello = l; stato.pratica = null; disegna(); },
              }, `${l} · ${n}`)))
        : null,
      el('div', { class: 'durata', style: 'margin-top:var(--s4)' },
        stato.livello
          ? el('button', {
              class: 'primario',
              onclick: () => { stato.livello = null; stato.pratica = null; disegna(); },
            }, 'Any level')
          : null,
        el('button', { class: 'secondario', onclick: () => vai('reading') },
          'Go to reading'),
        el('button', { class: 'secondario', onclick: () => vai('home') }, 'Home'))));
}

function disegnaFinePratica() {
  const p = stato.pratica;
  const c = $('#contenuto');
  const fatti = p.esercizi.filter((e) => e.aiuto !== undefined && !e.segnalato);
  const segnalati = p.esercizi.filter((e) => e.segnalato);
  const puliti = fatti.filter((e) => e.risolto && !e.aiuto);
  const conAiuto = fatti.filter((e) => e.risolto && e.aiuto);
  const mancati = fatti.filter((e) => !e.risolto);
  const costo = fatti.reduce((t, e) => t + (e.costo || 0), 0);

  if (!p.registrata) {
    p.registrata = true;
    api('/api/sessione', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        zona: 'practice',
        durata_scelta: stato.durata,
        secondi: Math.round((Date.now() - p.avviata) / 1000),
        viste: fatti.length,
        senza_aiuto: puliti.length,
        costo_eur: Number(costo.toFixed(5)),
        // `corretta` porta RISOLTO, non "la forma era giusta": al gradino 4 la
        // soluzione era sullo schermo, e contarla come sapere renderebbe la
        // scala di aiuto una decorazione.
        esercizi: fatti.map((e) => ({
          chiave: e.chiave, regola: e.regola, categoria: e.categoria,
          stimolo: e.stimolo, corretta: !!e.risolto, aiuto: e.aiuto || 0,
        })),
      }),
    }).catch(() => { /* il registro non deve mai bloccare la sessione */ });
  }

  const riga = (e) =>
    el('div', { class: 'riga' },
      el('div', { class: 'riga-capo' },
        el('strong', {}, e.regola || e.categoria),
        el('span', { class: 'provenienza' },
          e.risolto
            ? `solved at step ${e.aiuto}`
            : (e.aiuto >= 4 ? 'gave up' : 'wrong'))),
      el('div', { class: 'de', style: 'font-size:1rem;color:var(--matita)' }, e.stimolo));

  c.replaceChildren(
    el('section', { class: 'suggerimento' },
      el('h1', {}, 'Session done'),
      el('p', {}, `${puliti.length} of ${fatti.length} solved with no help`
        + (conAiuto.length ? ` · ${conAiuto.length} needed the ladder` : '')
        + (mancati.length ? ` · ${mancati.length} went back to the notebook` : '')
        + (segnalati.length
            ? ` · ${segnalati.length} dropped as broken, won't come back` : '')),
      el('div', { class: 'riepilogo-voti' },
        el('div', { class: 'voto-conteggio' },
          el('strong', {}, String(puliti.length)), el('span', {}, 'clean')),
        el('div', { class: 'voto-conteggio' },
          el('strong', {}, String(conAiuto.length)), el('span', {}, 'with help')),
        el('div', { class: 'voto-conteggio again' },
          el('strong', {}, String(mancati.length)), el('span', {}, 'missed')),
        el('div', { class: 'voto-conteggio' },
          el('strong', {}, costo.toFixed(3)), el('span', {}, '€ spent'))),
      el('div', { class: 'durata', style: 'margin-top:var(--s5)' },
        el('button', {
          class: 'primario',
          onclick: () => { stato.pratica = null; disegna(); },
        }, 'Another round'),
        el('button', { class: 'secondario', onclick: () => vai('home') }, 'Home'))),

    mancati.length
      ? el('section', {},
          el('h2', { style: 'font-size:1rem;margin:0 0 var(--s3)' },
            'Back in the queue'),
          ...mancati.map(riga))
      : null,

    conAiuto.length
      ? el('details', { style: 'margin-top:var(--s5)' },
          el('summary', { class: 'provenienza' },
            `${conAiuto.length} solved with help — they come back too`),
          ...conAiuto.map(riga))
      : null
  );
}

// ------------------------------------------------------------------ reference

/* La consultazione. Quattro popolazioni che oggi vivono in file che nessuno
 * apre: 301 regole, 1.069 vocaboli, 295 correzioni e ~2.400 passi di lezione.
 * L'ultima riga e' quella che non si trova altrove — 27 ore di lezione
 * trascritte, finora consultabili solo con Ctrl-F su un file alla volta.
 *
 * La distinzione visiva che conta non e' fra i quattro generi, e' fra
 * COLLEGAMENTO ESATTO e RISULTATO DI RICERCA. In F2 avevo agganciato regole ed
 * errori per somiglianza di nome e sbagliava 3 volte su 4, perche' una funzione
 * che sceglie in silenzio il miglior candidato non ha modo di dire «non lo so».
 * Qui l'esatto e il cercato stanno in due blocchi con due intestazioni diverse,
 * e sul cercato il punteggio resta in vista. */

const GENERI = [
  { id: 'regola',   nome: 'Rules',       etichetta: 'rule' },
  { id: 'vocabolo', nome: 'Words',       etichetta: 'word' },
  { id: 'errore',   nome: 'Corrections', etichetta: 'correction' },
  { id: 'passo',    nome: 'Lessons',     etichetta: 'lesson' },
];

const SPUNTI = ['Konjunktiv', 'Präposition Dativ', 'Perfekt sein', 'Adjektivdeklination',
                'Passiv', 'Nebensatz'];

function refVuoto() {
  return { q: '', genere: null, esito: null, conteggi: {}, aperto: null,
           attesa: null, caret: null };
}

stato.ref = refVuoto();

function vaiACercare(q) {
  stato.ref = { ...refVuoto(), q };
  vai('reference');
  cercaOra();
}

function cercaOra() {
  const r = stato.ref;
  const q = r.q.trim();
  if (!q) { r.esito = null; r.conteggi = {}; return disegna(); }
  const g = r.genere ? `&genere=${r.genere}` : '';
  api(`/api/cerca?q=${encodeURIComponent(q)}${g}`)
    .then((d) => {
      if (stato.ref.q.trim() !== q) return;      // una battuta piu' recente ha vinto
      stato.ref.esito = d;
      // I contatori per genere si aggiornano solo sulla ricerca NON filtrata:
      // con un filtro attivo la risposta contiene un genere solo, e gli altri
      // conteggi sparirebbero proprio mentre servono a tornare indietro.
      if (!stato.ref.genere) stato.ref.conteggi = d.per_genere || {};
      disegna();
    })
    .catch(mostraErrore);
}

function digitato(campo) {
  const r = stato.ref;
  r.q = campo.value;
  r.caret = campo.selectionStart;
  r.aperto = null;
  // L'indice risponde in ~20ms, ma una richiesta per battuta resta spreco: si
  // aspetta la fine della parola, non la fine della ricerca.
  clearTimeout(r.attesa);
  r.attesa = setTimeout(cercaOra, 120);
}

function disegnaConsultazione() {
  const c = $('#contenuto');
  const r = stato.ref;

  if (r.aperto) return disegnaDettaglio(c, r.aperto);

  const campo = el('input', {
    class: 'campo-cerca', type: 'search', autocomplete: 'off', spellcheck: 'false',
    value: r.q, placeholder: 'search rules, words, corrections, lessons…',
    oninput: (e) => digitato(e.target),
  });

  const conte = r.conteggi || {};
  const filtri = el('div', { class: 'filtri' },
    el('button', {
      class: 'filtro', 'aria-pressed': r.genere === null ? 'true' : 'false',
      onclick: () => { r.genere = null; cercaOra(); },
    }, 'All'),
    ...GENERI.map((g) =>
      el('button', {
        class: 'filtro', 'aria-pressed': r.genere === g.id ? 'true' : 'false',
        onclick: () => { r.genere = r.genere === g.id ? null : g.id; cercaOra(); },
      }, g.nome, conte[g.id] ? el('span', { class: 'n' }, ` ${conte[g.id]}`) : null))
  );

  c.replaceChildren(
    el('div', { class: 'cerca-riga' }, campo, filtri),
    r.esito ? disegnaRisultati(r.esito) : disegnaSpunti()
  );

  // Il campo si ricrea a ogni ridisegno, quindi il cursore va rimesso dov'era:
  // senza, correggere una lettera in mezzo alla parola lo sbatte in fondo a
  // ogni battuta, e la casella diventa inutilizzabile.
  campo.focus();
  const p = r.caret === null ? campo.value.length : Math.min(r.caret, campo.value.length);
  campo.setSelectionRange(p, p);
}

function disegnaSpunti() {
  // Una pagina vuota è un vicolo cieco: chi non sa cosa cercare non cerca.
  const b = stato.briefing;
  return el('section', {},
    el('p', { class: 'provenienza', style: 'margin-bottom:var(--s4)' },
      `${b.lezioni} lessons · ${b.vocaboli} words · ${b.errori} corrections, `
      + 'all searchable — including what Stefanie actually said.'),
    el('h2', { style: 'font-size:1rem;margin:0 0 var(--s3)' }, 'Start here'),
    el('div', { class: 'filtri' },
      ...SPUNTI.map((s) =>
        el('button', {
          class: 'filtro',
          onclick: () => { stato.ref.q = s; stato.ref.caret = null; cercaOra(); },
        }, el('span', { class: 'de', style: 'font-size:0.9375rem' }, s)))));
}

function disegnaRisultati(d) {
  if (!d.risultati.length) {
    return el('p', { class: 'vuoto' }, 'Nothing found.');
  }
  return el('section', {},
    el('p', { class: 'provenienza', style: 'margin:0 0 var(--s2)' },
      `${d.totale} of ${d.documenti} documents`),
    ...d.risultati.map(rigaRisultato));
}

function rigaRisultato(x) {
  const g = GENERI.find((y) => y.id === x.genere);
  return el('button', { class: 'risultato', onclick: () => apri(x) },
    el('span', { class: 'etichetta' }, g ? g.etichetta : x.genere),
    el('span', {},
      el('span', { class: 'risultato-capo' },
        el('span', { class: 'risultato-titolo' }, titoloDi(x)),
        el('span', { class: 'provenienza' }, sottotitoloDi(x))),
      el('span', { class: 'risultato-corpo' }, x.estratto)));
}

function titoloDi(x) {
  const m = x.meta || {};
  if (x.genere === 'vocabolo' && m.articolo) {
    return el('span', {},
      el('span', { class: classeGenere(m.articolo) }, m.articolo + ' '), x.titolo);
  }
  if (x.genere === 'errore') {
    return el('span', {},
      el('s', { style: 'color:var(--matita-tenue)' }, m.detto || '—'),
      el('span', { class: 'freccia' }, '→'), m.giusto);
  }
  return x.titolo;
}

function classeGenere(art) {
  return { der: 'der', die: 'die', das: 'das' }[(art || '').toLowerCase()] || '';
}

function sottotitoloDi(x) {
  const m = x.meta || {};
  if (x.genere === 'regola') return m.livello || '';
  if (x.genere === 'vocabolo') {
    return [m.livello, m.volte ? `${m.volte}×` : ''].filter(Boolean).join(' · ');
  }
  if (x.genere === 'errore') {
    return [m.categoria, m.quando, m.fonte === 'studio' ? 'from the app' : '']
      .filter(Boolean).join(' · ');
  }
  return m.lezione || '';
}

function apri(x) {
  api(`/api/dettaglio?genere=${x.genere}&id=${encodeURIComponent(x.id)}`)
    .then((d) => {
      if (d.errore) return mostraErrore(new Error(d.errore));
      stato.ref.aperto = d;
      disegna();
    })
    .catch(mostraErrore);
}

function disegnaDettaglio(c, d) {
  const x = d.documento;
  const m = x.meta || {};
  const g = GENERI.find((y) => y.id === x.genere);

  const corpo = [];

  if (x.genere === 'regola') {
    if (m.spiegazione) corpo.push(el('div', { class: 'blocco' },
      el('h2', {}, 'The rule'), el('p', {}, m.spiegazione)));
    if (m.errori_tipici) corpo.push(el('div', { class: 'blocco' },
      el('h2', {}, 'Where it usually goes wrong'), el('p', {}, m.errori_tipici)));
    if (m.eccezioni) corpo.push(el('div', { class: 'blocco' },
      el('h2', {}, 'Exceptions'), el('p', {}, m.eccezioni)));
    if (m.esempi && m.esempi.length) corpo.push(el('div', { class: 'blocco' },
      el('h2', {}, 'Examples'),
      el('ul', {}, ...m.esempi.map((e) => el('li', { class: 'de' }, e)))));

  } else if (x.genere === 'errore') {
    corpo.push(el('div', { class: 'blocco' },
      el('h2', {}, 'The rule you broke'),
      el('p', { class: 'de' }, m.regola || '—'),
      m.spiegazione ? el('p', {}, m.spiegazione) : null,
      m.esempio ? el('p', { class: 'de' }, m.esempio) : null));

  } else if (x.genere === 'vocabolo') {
    corpo.push(el('div', { class: 'blocco' },
      el('h2', {}, 'Meaning'),
      el('p', {}, [m.inglese, m.italiano].filter(Boolean).join(' · ') || '—'),
      m.plurale ? el('p', { class: 'provenienza' }, `plural: ${m.plurale}`) : null,
      m.esempio ? el('p', { class: 'de' }, m.esempio) : null));

  } else {
    corpo.push(el('div', { class: 'blocco' },
      el('h2', {}, 'What was said'),
      el('p', { class: 'de' }, d.testo)));
  }

  // Il blocco esatto e il blocco cercato NON si assomigliano, e l'intestazione
  // dice quale dei due stai leggendo.
  if (d.esatti && d.esatti.length) {
    corpo.push(el('div', { class: 'blocco' },
      el('h2', {}, x.genere === 'vocabolo'
        ? 'In your lessons' : 'The same rule, other times'),
      el('p', { class: 'nota' }, x.genere === 'vocabolo'
        ? 'Real sentences from the transcripts.'
        : 'Exact match on the rule — not a guess.'),
      ...d.esatti.map(rigaRisultato)));
  }

  if (d.simili && d.simili.length) {
    corpo.push(el('div', { class: 'blocco' },
      el('h2', {}, x.genere === 'regola' ? 'Corrections that may match' : 'Rules that may cover this'),
      el('p', { class: 'nota' },
        'Search results, ranked — the rule names in your notebook are free text, '
        + 'so this is a suggestion, not a link.'),
      ...d.simili.map(rigaRisultato)));
  }

  c.replaceChildren(
    el('button', { class: 'secondario', onclick: () => { stato.ref.aperto = null; disegna(); } },
      '← Back to results'),
    el('div', { class: 'dettaglio-capo', style: 'margin-top:var(--s4)' },
      el('div', { class: 'etichetta' }, g ? g.etichetta : x.genere),
      el('h1', {}, titoloDi(x)),
      el('div', { class: 'provenienza' }, sottotitoloDi(x))),
    ...corpo);
}

// ------------------------------------------------------------------ progress

/* «Sta funzionando?» — e la risposta facile sarebbe falsa.
 *
 * La cosa più semplice da disegnare qui sarebbe la curva delle correzioni per
 * lezione con una tendenza sopra. Misurata: 9,0 a lezione nella prima metà del
 * periodo, 10,0 nella seconda. Piatta. E anche se scendesse direbbe poco,
 * perché quel numero dipende da quanto hai parlato, da quanto Stefanie ha
 * corretto e da quanto bene Whisper ha trascritto: misura ESPOSIZIONE, non
 * padronanza.
 *
 * Quindi la curva c'è, perché è un dato vero e vederla piatta è informativo, ma
 * è etichettata per quello che è. Il progresso vero lo misura l'app — quanti
 * esercizi chiudi senza aiuto — e finché quei dati sono pochi questa zona lo
 * dice, invece di disegnarci sopra una freccia.
 *
 * SVG DISEGNATO QUI, NON GENERATO IN PYTHON (il piano diceva il contrario)
 * Un SVG generato lato server ha i colori cotti dentro: non può rispondere a
 * `prefers-color-scheme`, e questa app ha un tema scuro completo. Disegnandolo
 * qui i colori restano variabili CSS, il tema scuro funziona da solo, e
 * l'hover è gratis. Nessuna libreria in più — è lo stesso `createElementNS`
 * che già disegna le icone. */

const SVG = 'http://www.w3.org/2000/svg';

function svg(tag, attr = {}, ...figli) {
  const n = document.createElementNS(SVG, tag);
  for (const [k, v] of Object.entries(attr)) {
    if (v === null || v === undefined || v === false) continue;
    if (k.startsWith('on')) n.addEventListener(k.slice(2).toLowerCase(), v);
    else n.setAttribute(k, v === true ? '' : String(v));
  }
  for (const f of figli.flat()) {
    if (f === null || f === undefined || f === false) continue;
    n.append(f.nodeType ? f : document.createTextNode(String(f)));
  }
  return n;
}

function disegnaProgressi() {
  const c = $('#contenuto');
  const p = stato.progressi;

  if (!p) {
    c.replaceChildren(el('p', { class: 'vuoto' }, 'Adding it up…'));
    api('/api/progressi').then((d) => {
      stato.progressi = d;
      disegna();
      // Anki arriva dopo, e a pagina già disegnata: AnkiConnect paga ~2s fissi
      // a richiesta, e sono 2s di pagina bianca per un riquadro di contesto.
      api('/api/anki')
        .then((a) => { stato.anki = a; if (stato.zona === 'progress') disegna(); })
        .catch(() => { stato.anki = { disponibile: false }; });
    }).catch(mostraErrore);
    return;
  }

  const s = p.studio;
  c.replaceChildren(
    tesiProgressi(s),
    cifreProgressi(s),
    riquadroAnki(),
    graficoLezioni(p),
    graficoCategorie(p)
  );
}

/* La riga in cima non è un numero, è una frase: dice qual è la misura vera e
   se ce n'è abbastanza. Un cruscotto che apre con dei numeri lascia al lettore
   il lavoro di capire quale conta. */
function tesiProgressi(s) {
  let titolo, motivo;
  if (s.risposte < 20) {
    titolo = `${s.risposte} exercises answered — not a trend yet`;
    motivo = `The measure that actually tracks progress is how many you solve `
           + `with no help, and at which step you stop. It does not depend on `
           + `how much you talked in a lesson. ${s.servono_ancora} more answers `
           + `and this page starts showing the curve.`;
  } else if (s.tendenza_aiuto) {
    const d = s.tendenza_aiuto.dopo - s.tendenza_aiuto.prima;
    titolo = d < -0.2 ? 'You are needing less help'
           : d > 0.2 ? 'You are needing more help'
           : 'Help level is holding steady';
    motivo = `Average help step: ${s.tendenza_aiuto.prima} early on, `
           + `${s.tendenza_aiuto.dopo} lately. Lower is better — 0 means you `
           + `answered with nothing but the sentence.`;
  } else {
    titolo = `${s.senza_aiuto} of ${s.risposte} solved with no help`;
    motivo = 'Keep going — the curve needs a few more sessions to mean anything.';
  }

  return el('section', { class: 'suggerimento' },
    el('h1', {}, titolo),
    el('p', {}, motivo),
    el('div', { class: 'durata' },
      el('button', { class: 'primario', onclick: () => vai('practice') }, 'Practice'),
      s.da_rifare
        ? el('span', { class: 'provenienza' },
            `${s.da_rifare} rule${s.da_rifare > 1 ? 's' : ''} waiting to be redone`)
        : null));
}

function cifreProgressi(s) {
  const cifre = [
    { etichetta: 'Last studied',
      valore: s.giorni_da_ultima === null ? '—'
            : s.giorni_da_ultima === 0 ? 'today' : `${s.giorni_da_ultima}d ago`,
      nota: s.ultima ? `· ${s.ultima}` : '' },
    { etichetta: 'Answered', valore: s.risposte,
      nota: s.risposte ? `· ${s.senza_aiuto} with no help` : '' },
    { etichetta: 'Rules closed', valore: s.regole_chiuse,
      nota: `· ${s.regole_in_coda} still queued` },
    { etichetta: 'Own mistakes', valore: s.errori_dallo_studio,
      nota: '· made here, not in class' },
  ];
  return el('dl', { class: 'cifre' },
    ...cifre.map((k) =>
      el('div', { class: 'cifra' },
        el('dt', {}, k.etichetta),
        el('dd', {}, String(k.valore),
          k.nota ? el('small', {}, ' ' + k.nota) : null))));
}

function riquadroAnki() {
  const a = stato.anki;
  if (!a) return el('p', { class: 'provenienza' }, 'Checking Anki…');
  // Anki chiuso: il riquadro sparisce, il resto della pagina non se ne accorge.
  if (!a.disponibile) return null;
  return el('section', { class: 'riquadro-anki' },
    el('div', {},
      el('strong', {}, `${a.in_scadenza} cards due`),
      el('div', { class: 'provenienza' },
        `${a.in_studio} in rotation · ${a.nuove} never started · ${a.mazzo}`)),
    el('a', { class: 'secondario', href: 'anki://', style: 'text-decoration:none' },
      'Open Anki'));
}

// --- grafico 1: correzioni per lezione, a enfasi ----------------------
/* Due serie e non nove. Nove categorie nel tempo sono illeggibili, e la storia
 * è già nota: il 44% sono Kasus, Genus, Präposition. Quindi una serie è il
 * punto (ambra) e l'altra è contesto (grigio) — il colore de-enfatizzato è
 * validato contro l'ambra, non scelto a occhio: la coppia di partenza stava a
 * ΔE 13,4 a vista normale, sotto la soglia di 15 sotto cui due linee si
 * confondono anche con la vista piena. */
function graficoLezioni(p) {
  const dati = p.per_lezione;
  if (dati.length < 2) return null;

  const W = 640, H = 200, PL = 34, PR = 12, PT = 12, PB = 26;
  const max = Math.max(...dati.map((d) => d.totale), 1);
  const x = (i) => PL + (i / (dati.length - 1)) * (W - PL - PR);
  const y = (v) => H - PB - (v / max) * (H - PT - PB);

  const linea = (campo) => dati.map((d, i) => `${x(i)},${y(d[campo])}`).join(' ');

  const griglia = [0, Math.round(max / 2), max].map((v) =>
    svg('g', {},
      svg('line', { x1: PL, y1: y(v), x2: W - PR, y2: y(v), class: 'griglia' }),
      svg('text', { x: PL - 6, y: y(v) + 4, class: 'tacca', 'text-anchor': 'end' }, v)));

  // Hover: un punto per lezione, con area di presa larga quanto la fetta.
  const passo = (W - PL - PR) / (dati.length - 1);
  const prese = dati.map((d, i) =>
    svg('rect', {
      x: x(i) - passo / 2, y: PT, width: passo, height: H - PT - PB,
      fill: 'transparent',
      onmouseenter: (ev) => mostraSuggerimento(ev, [
        d.data, `${d.totale} corrections`,
        `${d.casi} case system · ${d.altri} other`]),
      onmouseleave: nascondiSuggerimento,
    }));

  const c = p.confronto_lezioni;
  return el('section', { class: 'blocco' },
    el('h2', {}, 'Corrections per lesson'),
    el('p', { class: 'nota' },
      'This measures exposure, not mastery: the count depends on how much you '
      + 'spoke and how much Stefanie corrected.'
      + (c ? ` It has not moved — ${c.prima} per lesson early on, ${c.dopo} lately.` : '')),
    el('div', { class: 'legenda' },
      el('span', { class: 'chiave' }, el('i', { class: 'campione casi' }), 'Kasus · Genus · Präposition'),
      el('span', { class: 'chiave' }, el('i', { class: 'campione altri' }), 'everything else')),
    el('div', { class: 'tela' },
      svg('svg', { viewBox: `0 0 ${W} ${H}`, role: 'img',
                   'aria-label': 'Corrections per lesson over time' },
        ...griglia,
        svg('polyline', { points: linea('altri'), class: 'linea altri' }),
        svg('polyline', { points: linea('casi'), class: 'linea casi' }),
        svg('text', { x: PL, y: H - 8, class: 'tacca' }, dati[0].data.slice(5)),
        svg('text', { x: W - PR, y: H - 8, class: 'tacca', 'text-anchor': 'end' },
            dati[dati.length - 1].data.slice(5)),
        ...prese)),
    tabellaDi('Corrections per lesson',
      ['Lesson', 'Case system', 'Other', 'Total'],
      dati.map((d) => [d.data, d.casi, d.altri, d.totale])));
}

// --- grafico 2: per categoria, barre orizzontali, un colore solo ------
/* Categorie nominali: una barra, un colore. Colorarle a gradiente per valore
 * rifarebbe con la tinta ciò che la lunghezza già dice. Orizzontali perché i
 * nomi tedeschi sono lunghi e in verticale si spezzerebbero. */
function graficoCategorie(p) {
  const dati = p.per_categoria;
  if (!dati.length) return null;
  const max = Math.max(...dati.map((d) => d.quante), 1);

  return el('section', { class: 'blocco' },
    el('h2', {}, 'Where the mistakes are'),
    el('p', { class: 'nota' },
      'Corrections from your lessons, by category. Kasus, Genus and Präposition '
      + 'are three sides of the same system.'),
    el('div', { class: 'barre' },
      ...dati.map((d) =>
        el('div', { class: 'barra-riga' },
          el('span', { class: 'barra-nome' }, d.nome),
          el('span', { class: 'barra-pista' },
            el('i', { class: 'barra-fatto', style: `width:${(d.quante / max) * 100}%` })),
          el('span', { class: 'barra-valore' }, String(d.quante))))),
    tabellaDi('Mistakes by category', ['Category', 'Corrections'],
      dati.map((d) => [d.nome, d.quante])));
}

/* Ogni grafico ha la sua tabella. Non è un extra di cortesia: è l'unico modo
   di leggere i valori esatti, e l'unico che funziona senza vedere i colori. */
function tabellaDi(titolo, intestazioni, righe) {
  return el('details', { class: 'tabella-vista' },
    el('summary', { class: 'provenienza' }, 'Table view'),
    el('table', {},
      el('caption', { class: 'provenienza' }, titolo),
      el('thead', {}, el('tr', {}, ...intestazioni.map((h) => el('th', {}, h)))),
      el('tbody', {},
        ...righe.map((r) => el('tr', {}, ...r.map((v) => el('td', {}, String(v))))))));
}

function mostraSuggerimento(ev, righe) {
  let t = $('#suggerimento');
  if (!t) {
    t = el('div', { id: 'suggerimento', class: 'suggerimento-fluttuante' });
    document.body.append(t);
  }
  t.replaceChildren(...righe.map((r, i) =>
    el('div', { class: i ? 'provenienza' : null }, r)));
  const r = ev.target.getBoundingClientRect();
  t.style.left = `${r.left + r.width / 2}px`;
  t.style.top = `${r.top - 8}px`;
  t.hidden = false;
}

function nascondiSuggerimento() {
  const t = $('#suggerimento');
  if (t) t.hidden = true;
}

// ------------------------------------------------------------------ kursbuch

async function avviaKursbuch() {
  const d = await api('/api/libro/lektioni');
  stato.kursbuch = { lektioni: d.lektioni, aperta: null };
}

function disegnaKursbuch() {
  const c = $('#contenuto');
  if (!stato.kursbuch) {
    c.replaceChildren(el('p', { class: 'vuoto' }, 'Loading the course book…'));
    avviaKursbuch().then(disegna).catch(mostraErrore);
    return;
  }

  const { lektioni, aperta } = stato.kursbuch;
  // "Sei qui": la prima Lektion senza pratica registrata, o l'ultima se le
  // hai fatte tutte — non e' un dato del server, e' una lettura del client
  // sullo stesso elenco che gia' ha.
  const primaAperta = lektioni.find((l) => l.pratica_pct === null) || lektioni[lektioni.length - 1];
  const correnteNumero = aperta ?? (primaAperta ? primaAperta.numero : null);

  c.replaceChildren(
    el('section', { class: 'kursbuch-percorso' },
      ...lektioni.map((l) => {
        const e_corrente = l.numero === correnteNumero;
        const nodo = el('button', {
          class: 'kursbuch-tappa' + (e_corrente ? ' kursbuch-tappa-corrente' : ''),
          onclick: () => { stato.kursbuch.aperta = l.numero; disegna(); vaiDettaglioLektion(l.numero); },
        },
          el('span', { class: 'kursbuch-numero' }, String(l.numero)),
          el('span', { class: 'kursbuch-titolo' }, l.titolo || `Lektion ${l.numero}`),
        );
        if (!e_corrente) return nodo;

        return el('div', { class: 'kursbuch-tappa-espansa' },
          nodo,
          disegnaBarra('Your practice', l.pratica_pct),
          disegnaCollegate(l.n_lezioni_collegate),
        );
      })
    )
  );
}

function disegnaBarra(etichetta, pct) {
  if (pct === null || pct === undefined) {
    return el('p', { class: 'provenienza' }, `${etichetta}: not enough data yet`);
  }
  // Riusa il pattern esistente .avanzamento + .barra/.barra i (vedi lettura e
  // allenamento) invece di inventare classi kursbuch-* — stessa forma di DOM,
  // stile gia' definito in stile.css, niente CSS nuovo da scrivere e tenere
  // sincrono.
  return el('div', {},
    el('div', { class: 'avanzamento' },
      el('span', {}, etichetta), el('span', {}, `${pct}%`)),
    el('div', { class: 'barra' },
      el('i', { style: `width:${pct}%` })));
}

// `copertura_pct` (dal server) e' 0 o 100 fisso — non una vera percentuale
// (vedi il commento in do/uscite/web.py:libro_lektioni). A differenza di
// pratica_pct non e' mai `null`, quindi non passerebbe mai per il ramo "not
// enough data" di disegnaBarra: mostrerebbe sempre un numero sicuro anche
// quando il dato dietro e' debole. Qui si mostra invece il conteggio vero
// delle lezioni collegate — meno appariscente, ma non finto.
function disegnaCollegate(n) {
  return el('div', { class: 'avanzamento' },
    el('span', {}, 'Covered with Stefanie'),
    el('span', {}, n ? `${n} lesson${n === 1 ? '' : 's'} touched this topic` : 'none yet'));
}

async function avviaDettaglioLektion(numero) {
  const d = await api(`/api/libro/lektion/${numero}`);
  stato.kursbuchDettaglio = d;
}

function vaiDettaglioLektion(numero) {
  stato.kursbuchDettaglioNumero = numero;
  stato.zona = 'kursbuch-dettaglio';
  stato.kursbuchDettaglio = null;
  disegna();
}

function disegnaKursbuchDettaglio() {
  const c = $('#contenuto');
  const numero = stato.kursbuchDettaglioNumero ?? stato.kursbuch?.aperta;
  if (!stato.kursbuchDettaglio) {
    c.replaceChildren(el('p', { class: 'vuoto' }, 'Loading Lektion…'));
    avviaDettaglioLektion(numero).then(disegna).catch(mostraErrore);
    return;
  }

  const d = stato.kursbuchDettaglio;
  c.replaceChildren(
    el('button', { class: 'secondario', onclick: () => { stato.zona = 'kursbuch'; disegna(); } },
      '← Back to Kursbuch'),
    el('h1', {}, `Lektion ${d.numero} — ${d.titolo}`),

    d.lezioni_collegate.length
      ? el('section', {},
          el('h2', { style: 'font-size:1rem' }, 'Your lessons on similar topics'),
          ...d.lezioni_collegate.map((lc) =>
            el('div', { class: 'riga' },
              el('div', { class: 'riga-capo' }, lc.data_lezione),
              el('div', { class: 'provenienza' }, lc.motivo))))
      : null,

    ...d.pagine.map((pag) => el('article', { class: 'esercizio' },
      el('img', {
        src: `/api/libro/pagina/${pag.chiave.split(':')[0]}/${pag.chiave.split(':')[1]}`,
        loading: 'lazy', style: 'max-width:100%;border-radius:var(--r2);margin-bottom:var(--s3)',
        alt: `Page ${pag.chiave}`,
      }),
      ...pag.esercizi.filter((e) => e.soluzione).map((e) =>
        el('div', { class: 'riga' },
          el('p', { class: 'stimolo' }, e.stimolo),
          el('p', { class: 'provenienza' }, `→ ${e.soluzione}`)))
    ))
  );
}

// ------------------------------------------------------------------ listening

async function avviaAscolto() {
  const d = await api('/api/libro/listening?n=10');
  stato.ascolto = { esercizi: d.esercizi, totali: d.totali, i: 0, fase: 'domanda', soluzione: null };
}

function disegnaAscolto() {
  const c = $('#contenuto');
  const a = stato.ascolto;
  if (!a) {
    c.replaceChildren(el('p', { class: 'vuoto' }, 'Loading listening exercises…'));
    avviaAscolto().then(disegna).catch(mostraErrore);
    return;
  }

  const e = a.esercizi[a.i];
  if (!e) {
    c.replaceChildren(el('p', { class: 'vuoto' },
      a.totali === 0
        ? 'No listening exercises ready yet — run libro --risolvi-esercizi first.'
        : "That's all for this session."));
    return;
  }

  if (a.fase === 'rivelato') {
    c.replaceChildren(
      el('article', { class: 'esercizio' },
        el('p', { class: 'consegna' }, e.consegna),
        el('p', { class: 'stimolo' }, e.stimolo),
        el('p', { class: 'traduzione' }, `→ ${a.soluzione}`),
        el('div', { class: 'voti' },
          el('button', { class: 'voto good', onclick: () => avantiAscolto(true) }, 'Got it right'),
          el('button', { class: 'voto again', onclick: () => avantiAscolto(false) }, 'Got it wrong'),
        )
      )
    );
    return;
  }

  c.replaceChildren(
    el('div', { class: 'avanzamento' },
      el('span', {}, `${a.i + 1} of ${a.esercizi.length}`)),
    el('article', { class: 'esercizio' },
      el('p', { class: 'consegna' }, e.consegna),
      el('p', { class: 'stimolo' }, e.stimolo),
      el('button', { class: 'primario', onclick: () => rivelaAscolto() }, 'Show answer'))
  );
}

async function rivelaAscolto() {
  // Sola lettura: niente campo `corretta` nel corpo. do/uscite/web.py
  // (libro_risposta) distingue "corretta" assente da "corretta: false" — la
  // prima non scrive nel registro, la seconda si'. Il voto vero arriva solo
  // dopo, da avantiAscolto(), che e' quindi l'UNICA scrittura per esercizio.
  const a = stato.ascolto;
  const e = a.esercizi[a.i];
  const r = await api('/api/libro/risposta', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      lektion: e.lektion, chiave_pagina: e.chiave_pagina,
      indice_esercizio: e.indice_esercizio,
    }),
  });
  a.soluzione = r.soluzione;
  a.fase = 'rivelato';
  disegna();
}

function avantiAscolto(corretta) {
  const a = stato.ascolto;
  const e = a.esercizi[a.i];
  api('/api/libro/risposta', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      lektion: e.lektion, chiave_pagina: e.chiave_pagina,
      indice_esercizio: e.indice_esercizio, corretta,
    }),
  }).catch(() => {});  // il voto e' gia' mostrato all'utente, un fallimento di rete qui non deve bloccarlo
  a.i += 1;
  a.fase = 'domanda';
  a.soluzione = null;
  disegna();
}

// ------------------------------------------------------------------ exam

/* «A che punto sono per il B2» — e la risposta ha due metà che non si sommano.
 *
 * In alto sta il MODELLSATZ: il PDF ufficiale del Goethe, cronometrato, fatto
 * da te. È l'unico numero esterno che questo sistema accetta, e il tuo stesso
 * `scadenze.md` spiega perché: «esame.py è una metrica auto-prodotta dallo
 * stesso sistema che genera le lezioni — misura cosa hai incontrato, non cosa
 * sai produrre sotto pressione in 90 minuti».
 *
 * Sotto sta la gap analysis: i 22 temi B2 e la prontezza per modulo. È utile
 * per decidere COSA studiare, e non è un punteggio. Le due metà stanno nella
 * stessa pagina ma sono etichettate diversamente, e non si mescolano mai in un
 * numero solo — che è esattamente la tentazione da evitare qui. */

function disegnaEsame() {
  const c = $('#contenuto');
  const e = stato.esame;

  if (!e) {
    c.replaceChildren(el('p', { class: 'vuoto' }, 'Loading…'));
    api('/api/esame').then((d) => { stato.esame = d; disegna(); }).catch(mostraErrore);
    return;
  }
  if (stato.scrittura) return disegnaScrittura(c);

  c.replaceChildren(
    riquadroModellsatz(e.modellsatz),
    sezioneScrittura(e),
    sezioneTemi(e),
    sezioneModuli(e)
  );
}

function riquadroModellsatz(m) {
  const nessuno = m.quante === 0;
  return el('section', {},
    el('section', { class: 'suggerimento' },
      el('h1', {}, nessuno ? 'No Modellsatz on record yet'
                           : `${m.moduli_superati} of ${m.moduli_misurati} modules above ${m.soglia}`),
      el('p', {}, nessuno
        ? 'This is the only external measure the system accepts. Do the official '
          + 'paper under time, then record the four scores here.'
        : m.pendenza_leggibile
          ? 'The number that matters is the slope between attempts, not the level.'
          : 'One attempt is a starting point, not a trend. The second one is what '
            + 'measures whether the method is working.'),
      el('div', { class: 'durata' },
        el('a', { class: 'primario', href: m.fonte, target: '_blank',
                  rel: 'noopener', style: 'text-decoration:none' },
          'Official Modellsatz (PDF)'),
        el('button', {
          class: 'secondario',
          onclick: () => { stato.registraMs = !stato.registraMs; disegna(); },
        }, stato.registraMs ? 'Cancel' : 'Record an attempt'))),

    stato.registraMs ? moduloRegistrazione(m) : null,

    el('div', { class: 'cifre' },
      ...m.moduli.map((x) =>
        el('div', { class: 'cifra' },
          el('dt', {}, x.nome, el('span', { class: 'livello' }, `${x.minuti}′`)),
          el('dd', {},
            x.ultimo === null ? '—' : String(x.ultimo),
            x.ultimo === null
              ? el('small', {}, ' not attempted')
              : el('small', {},
                  ` /${m.pieno}`,
                  x.delta === null ? '' : ` · ${x.delta > 0 ? '+' : ''}${x.delta}`)),
          el('div', { class: 'provenienza' }, x.descrizione)))),

    m.prove.length
      ? el('details', { style: 'margin-bottom:var(--s6)' },
          el('summary', { class: 'provenienza' }, `${m.prove.length} attempt(s) on record`),
          el('table', {},
            el('thead', {}, el('tr', {},
              ...['Date', ...m.moduli.map((x) => x.nome), 'Timed'].map((h) => el('th', {}, h)))),
            el('tbody', {},
              ...m.prove.map((p) =>
                el('tr', {},
                  el('td', {}, p.data),
                  ...m.moduli.map((x) => el('td', {}, String(p.punteggi[x.id] ?? '—'))),
                  el('td', {}, p.cronometrato ? 'yes' : 'no'))))))
      : null);
}

function moduloRegistrazione(m) {
  const campi = {};
  const oggi = new Date().toISOString().slice(0, 10);
  const data = el('input', { class: 'campo', type: 'date', value: oggi,
                             style: 'font-family:var(--font-ui);font-size:1rem' });
  const timed = el('input', { type: 'checkbox', checked: true });

  return el('section', { class: 'esercizio' },
    el('p', { class: 'consegna' },
      'Scores out of 100 per module. ',
      el('b', {}, 'Leave blank what you did not attempt'),
      ' — a zero would look like a collapse later.'),
    el('div', { class: 'barre' },
      ...m.moduli.map((x) => {
        const campo = el('input', {
          class: 'campo', type: 'number', min: '0', max: '100',
          placeholder: '—',
          style: 'font-family:var(--font-mono);font-size:1rem;text-align:right',
        });
        campi[x.id] = campo;
        return el('div', { class: 'barra-riga' },
          el('span', { class: 'barra-nome' }, x.nome),
          campo,
          el('span', { class: 'barra-valore' }, `/${m.pieno}`));
      })),
    el('div', { class: 'risposta-riga' },
      el('label', { class: 'provenienza' }, timed, ' done under exam time'),
      data,
      el('button', {
        class: 'primario',
        onclick: () => {
          const punteggi = {};
          for (const [k, v] of Object.entries(campi)) {
            if (v.value !== '') punteggi[k] = Number(v.value);
          }
          api('/api/modellsatz', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
              data: data.value, cronometrato: timed.checked, punteggi,
            }),
          }).then(() => {
            stato.registraMs = false;
            stato.esame = null;
            disegna();
          }).catch(mostraErrore);
        },
      }, 'Save')));
}

function sezioneScrittura(e) {
  return el('section', { class: 'blocco' },
    el('h2', {}, 'Writing practice'),
    el('p', { class: 'nota' },
      'Goethe format, but no score: a task written by a model and marked by the '
      + 'same model is not a measurement. What it does give you is corrections — '
      + 'and every one of them goes into your notebook and comes back as a drill.'),
    el('div', { class: 'durata' },
      ...e.tipi_prova.map((t) =>
        el('button', {
          class: 'secondario',
          onclick: () => avviaScrittura(t.id),
        }, t.nome, el('span', { class: 'livello' }, `${t.minuti}′`)))),
    e.scritte.length
      ? el('details', { style: 'margin-top:var(--s4)' },
          el('summary', { class: 'provenienza' },
            `${e.scritte.length} written so far`),
          ...e.scritte.map((s) =>
            el('div', { class: 'riga' },
              el('div', { class: 'riga-capo' },
                el('strong', {}, s.compito?.titolo || '—'),
                el('span', { class: 'provenienza' },
                  `${s.parole} words · ${s.errori} corrections · ${(s.quando || '').slice(0, 10)}`)),
              el('div', { class: 'provenienza' }, s.sintesi || ''))))
      : null);
}

function avviaScrittura(tipo) {
  stato.scrittura = { fase: 'carico', tipo, testo: '', esito: null };
  disegna();
  api(`/api/compito?tipo=${tipo}`)
    .then((c) => { stato.scrittura = { fase: 'scrivo', tipo, compito: c, testo: '', esito: null }; disegna(); })
    .catch(mostraErrore);
}

function disegnaScrittura(c) {
  const s = stato.scrittura;
  if (s.fase === 'carico') {
    return c.replaceChildren(el('p', { class: 'vuoto' }, 'Writing you a task…'));
  }
  if (s.fase === 'esito') return disegnaCorrezione(c, s);

  const t = s.compito;
  const area = el('textarea', {
    class: 'campo area', rows: '14', lang: 'de', spellcheck: 'false',
    placeholder: `Write about ${t.parole} words in German…`,
    oninput: (ev) => { s.testo = ev.target.value; aggiornaConteggio(); },
  });
  area.value = s.testo;

  const conteggio = el('span', { class: 'provenienza' });
  function aggiornaConteggio() {
    const n = s.testo.trim() ? s.testo.trim().split(/\s+/).length : 0;
    conteggio.textContent = `${n} / ~${t.parole} words`;
  }

  c.replaceChildren(
    el('button', { class: 'secondario',
                   onclick: () => { stato.scrittura = null; disegna(); } },
      '← Back'),
    el('article', { class: 'esercizio', style: 'margin-top:var(--s4)' },
      el('p', { class: 'consegna' },
        el('b', {}, t.nome), ` · ~${t.parole} words · ${t.minuti} min`),
      el('p', { class: 'de', style: 'font-size:1.125rem' }, t.situazione),
      el('p', { class: 'de', style: 'font-size:1.125rem;font-weight:600' }, t.consegna),
      el('ul', { class: 'de', style: 'font-size:1.0625rem' },
        ...t.punti.map((p) => el('li', {}, p))),
      t.aiuto_en
        ? el('details', { class: 'scheda' },
            el('summary', {}, 'What is being asked (English)'),
            el('p', {}, t.aiuto_en))
        : null),
    area,
    barraUmlaut(area),
    el('div', { class: 'risposta-riga' },
      el('button', {
        class: 'primario',
        onclick: () => {
          s.fase = 'correggo';
          disegna();
          api('/api/correggi', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ compito: t, testo: s.testo }),
          }).then((r) => {
            if (r.errore) { s.fase = 'scrivo'; disegna(); return mostraErrore(new Error(r.errore)); }
            s.esito = r; s.fase = 'esito'; disegna();
          }).catch((err) => { s.fase = 'scrivo'; disegna(); mostraErrore(err); });
        },
      }, s.fase === 'correggo' ? 'Reading it…' : 'Hand it in'),
      conteggio)
  );
  aggiornaConteggio();
}

function disegnaCorrezione(c, s) {
  const x = s.esito;
  c.replaceChildren(
    el('button', { class: 'secondario',
                   onclick: () => { stato.scrittura = null; stato.esame = null; disegna(); } },
      '← Back to exam'),
    el('section', { class: 'suggerimento', style: 'margin-top:var(--s4)' },
      el('h1', {}, `${x.errori.length} corrections`),
      el('p', {}, x.sintesi),
      el('p', { class: 'provenienza' },
        `${x.parole} words · ${x.nel_quaderno} added to your notebook — `
        + `they will come back as exercises · ${(x.costo_eur || 0).toFixed(4)} €`)),

    x.errori.length
      ? el('section', { class: 'blocco' },
          el('h2', {}, 'What to fix'),
          ...x.errori.map((e) =>
            el('div', { class: 'riga' },
              el('div', { class: 'riga-capo' },
                el('span', { class: 'de', style: 'font-size:1.0625rem' },
                  el('s', { style: 'color:var(--matita-tenue)' }, e.kevin_said || '—'),
                  el('span', { class: 'freccia' }, '→'),
                  e.correction),
                el('span', { class: 'provenienza' }, e.category)),
              el('div', { class: 'provenienza' },
                el('strong', {}, e.rule || ''), e.explanation_en ? ' · ' + e.explanation_en : ''))))
      : null,

    el('section', { class: 'blocco' },
      el('h2', {}, 'The four criteria'),
      el('p', { class: 'nota' },
        'The dimensions the Goethe grid uses. No score — see above.'),
      ...x.criteri.map((k) =>
        el('div', { class: 'riga' },
          el('div', { class: 'riga-capo' }, el('strong', {}, k.nome)),
          el('div', {}, k.commento))))
  );
}

function sezioneTemi(e) {
  const c = e.conteggio_temi;
  const stile = { mancante: 'manca', parziale: 'parziale', coperto: 'coperto' };
  return el('section', { class: 'blocco' },
    el('h2', {}, 'B2 grammar, topic by topic'),
    el('p', { class: 'nota' },
      `${c.mancante} never covered · ${c.parziale} partial · ${c.coperto} covered. `
      + 'From the gap analysis — this says what your lessons touched, not what you '
      + 'can produce.'
      + (e.gap_generato ? ` Last run ${e.gap_generato.slice(0, 10)}.` : '')),
    ...e.temi.map((t) =>
      el('div', { class: 'riga' },
        el('div', { class: 'riga-capo' },
          el('span', { class: `stato ${stile[t.stato] || ''}` }, t.stato),
          el('span', { class: 'de', style: 'font-size:1.0625rem' }, t.tema)),
        t.nota ? el('div', { class: 'provenienza' }, t.nota) : null,
        el('button', { class: 'gradino-tasto', onclick: () => vaiACercare(t.tema) },
          'Look it up'),
        // Puntatore verso il Kursbuch, solo se esame() ha trovato un esempio
        // in una Lektion — vedi do/uscite/web.py:esame(). Stesso stile del
        // tasto "Look it up" qui sopra: e' un'altra scorciatoia di
        // navigazione sulla stessa riga, non un componente nuovo.
        t.lektion_libro
          ? el('button', { class: 'gradino-tasto', onclick: () => vaiDettaglioLektion(t.lektion_libro) },
              `→ Lektion ${t.lektion_libro}`)
          : null)));
}

function sezioneModuli(e) {
  if (!e.moduli_gap.length) return null;
  return el('section', { class: 'blocco' },
    el('h2', {}, 'Readiness by module — the estimate, not the measure'),
    el('p', { class: 'nota' },
      'Produced by the system from its own data. The real number is the '
      + 'Modellsatz at the top of this page.'),
    ...e.moduli_gap.map((m) =>
      el('div', { class: 'riga' },
        el('div', { class: 'riga-capo' },
          el('strong', {}, m.modulo),
          el('span', { class: `stato ${m.prontezza === 'probabile' ? 'coperto'
                                     : m.prontezza === 'improbabile' ? 'manca' : 'parziale'}` },
            m.prontezza)),
        el('div', { class: 'provenienza' }, m.perche))));
}

// ------------------------------------------------------------------ umlaut

function barraUmlaut(campo) {
  const tasti = ['ä', 'ö', 'ü', 'ß', 'Ä', 'Ö', 'Ü'];
  return el('div', { class: 'umlaut' },
    ...tasti.map((t) =>
      el('button', {
        type: 'button', tabindex: '-1',
        onclick: () => {
          const p = campo.selectionStart ?? campo.value.length;
          campo.value = campo.value.slice(0, p) + t + campo.value.slice(campo.selectionEnd ?? p);
          campo.focus();
          campo.setSelectionRange(p + 1, p + 1);
        },
      }, t))
  );
}

// ------------------------------------------------------------------ tastiera

document.addEventListener('keydown', (e) => {
  const dentroCampo = ['INPUT', 'TEXTAREA'].includes(document.activeElement?.tagName);
  const s = stato.sessione;

  if (e.key === 'Escape') { if (!dentroCampo) vai('home'); return; }

  // "/" porta alla consultazione da qualunque zona. E' la convenzione di ogni
  // strumento con una ricerca, e serve proprio a meta' esercizio: la domanda
  // «come si diceva…?» arriva mentre stai facendo altro.
  if (e.key === '/' && !dentroCampo) {
    e.preventDefault();
    return vai('reference');
  }

  // In allenamento Invio fa avanzare anche dalla schermata di esito, dove il
  // campo non esiste piu' e il fuoco e' sul documento.
  if (stato.zona === 'practice') {
    const p = stato.pratica;
    if (!p || !p.esercizi[p.i]) return;
    if (p.fase === 'esito' && (e.key === 'Enter' || e.key === ' ')) {
      e.preventDefault();
      return avantiPratica();
    }
    // Il 5 segnala, come in lettura. Dentro il campo no: li' si sta scrivendo.
    if (e.key === '5' && !dentroCampo) {
      e.preventDefault();
      return segnalaEsercizio(p.esercizi[p.i]);
    }
    return;
  }

  if (stato.zona !== 'reading' || !s || dentroCampo) return;

  if (s.fase === 'domanda') {
    const f = s.frasi[s.i];
    const i = LETTERE.indexOf(e.key.toUpperCase());
    if (i >= 0 && f?.opzioni?.[i]) { e.preventDefault(); return scopri(f.opzioni[i]); }
    if (e.key === ' ' || e.key === 'Enter') { e.preventDefault(); return scopri(null); }
  }

  // I voti 1-4 arrivano solo dopo lo scoprimento — e' l'ordine che li rende
  // una misura invece che una previsione. Il 5 non e' un voto: segnala la frase.
  if (s.fase === 'risposta') {
    if (['1', '2', '3', '4'].includes(e.key)) {
      e.preventDefault();
      return vota(Number(e.key));
    }
    if (e.key === '5') {
      e.preventDefault();
      return segnalaFrase(s.frasi[s.i]);
    }
  }
});

// ------------------------------------------------------------------ avvio

function mostraErrore(err) {
  $('#contenuto').replaceChildren(
    el('div', { class: 'errore-app' },
      el('strong', {}, 'Something went wrong'),
      el('p', {}, String(err.message || err)))
  );
}

function disegna() {
  stato.avanza = null;
  if (stato.zona === 'home') return disegnaHome();
  if (stato.zona === 'reading') return disegnaLettura();
  if (stato.zona === 'practice') return disegnaPratica();
  if (stato.zona === 'reference') return disegnaConsultazione();
  if (stato.zona === 'progress') return disegnaProgressi();
  if (stato.zona === 'exam') return disegnaEsame();
  if (stato.zona === 'kursbuch') return disegnaKursbuch();
  if (stato.zona === 'kursbuch-dettaglio') return disegnaKursbuchDettaglio();
  if (stato.zona === 'listening') return disegnaAscolto();
  $('#contenuto').replaceChildren(el('p', { class: 'vuoto' }, 'Not built yet.'));
}

function disegnaPie() {
  const b = stato.briefing;
  // I tasti cambiano con la zona: mostrarli tutti insieme sarebbe una legenda
  // di cose che qui non funzionano.
  const perZona = {
    practice: [el('kbd', {}, '⏎'), ' check, then next'],
    reading: [el('kbd', {}, 'A'), '–', el('kbd', {}, 'D'), ' answer · ',
              el('kbd', {}, '1'), '–', el('kbd', {}, '4'), ' rate · ',
              el('kbd', {}, '5'), ' flag'],
    reference: [el('kbd', {}, '⏎'), ' open a result'],
  };
  const tasti = [el('kbd', {}, 'Esc'), ' home · ', el('kbd', {}, '/'), ' search',
                 ...(perZona[stato.zona] ? [' · ', ...perZona[stato.zona]] : [])];

  $('#pieplista').replaceChildren(
    el('span', {}, `${b.lezioni} lessons · ${b.vocaboli} words · ${b.errori} corrections`),
    el('span', {}, b.ultima_lezione ? `last lesson ${b.ultima_lezione}` : ''),
    el('span', { style: 'margin-left:auto' }, ...tasti)
  );
}

(async function avvio() {
  try {
    stato.briefing = await api('/api/stato');
  } catch (err) { return mostraErrore(err); }
  const h = location.hash.slice(1);
  if (ZONE.some((z) => z.id === h && z.pronta)) stato.zona = h;
  disegnaZone();
  disegnaPie();
  disegna();
})();
