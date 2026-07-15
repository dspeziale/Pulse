# Pulse — Requisiti

Documento: `05_requisiti.md`
Autore: AGENTE 1 — ANALISTA
Data: 2026-07-15

Requisiti funzionali `RF-###` e non funzionali `RNF-###`, numerati e tracciabili verso casi d'uso (`04_casi_uso.md`), API (`docs/api/DOCUMENTO_API.md`) e dati (`docs/database/DOCUMENTO_DATABASE.md`).

---

## 1. Requisiti Funzionali (RF)

### Autenticazione
| ID | Requisito | Tracciabilità |
|---|---|---|
| RF-001 | Il sistema deve autenticare gli utenti con username e password. | UC-01 |
| RF-002 | Il sistema deve emettere token di accesso a breve durata e refresh token revocabili. | UC-01, UC-02 |
| RF-003 | Il sistema deve consentire refresh e logout (revoca sessione). | UC-02 |
| RF-004 | Il sistema deve consentire all'utente di cambiare la propria password. | UC-03 |
| RF-005 | Il sistema deve bloccare l'account dopo N tentativi falliti (N configurabile). | UC-01, UC-95 |

### Autorizzazione / RBAC
| ID | Requisito | Tracciabilità |
|---|---|---|
| RF-010 | Ogni operazione deve essere protetta da un permesso granulare. | 06_rbac.md |
| RF-011 | Gli utenti devono poter avere uno o più ruoli; i ruoli aggregano permessi. | UC-14, UC-23 |
| RF-012 | Il sistema deve fornire ruoli predefiniti non eliminabili. | 06_rbac.md |
| RF-013 | Il sistema deve consentire la creazione di ruoli personalizzati con permessi assegnabili. | UC-21, UC-23 |
| RF-014 | Il catalogo dei permessi è fisso e consultabile; non creabile a runtime. | UC-20 |

### Gestione utenti/ruoli/permessi
| ID | Requisito | Tracciabilità |
|---|---|---|
| RF-020 | CRUD utenti con abilitazione/disabilitazione e reset password. | UC-10..14 |
| RF-021 | Deve sempre esistere almeno un Super Amministratore attivo. | UC-12, UC-13 |
| RF-022 | CRUD ruoli personalizzati e assegnazione permessi. | UC-21..23 |
| RF-023 | Consultazione catalogo permessi. | UC-20 |

### Gestione Probe
| ID | Requisito | Tracciabilità |
|---|---|---|
| RF-030 | Il sistema deve consentire l'enrollment sicuro di una Probe con token monouso. | UC-31 |
| RF-031 | CRUD della definizione di Probe. | UC-30..33 |
| RF-032 | Rotazione e revoca delle credenziali/certificato di una Probe. | UC-34 |
| RF-033 | Visualizzazione stato/liveness di ciascuna Probe. | UC-35 |
| RF-034 | Assegnazione dei sistemi monitorati a una Probe. | UC-41, UC-42 |
| RF-035 | La Probe deve poter scaricare dal Server la propria configurazione (sistemi + polling). | UC-41..43 |

### Gestione sistemi monitorati
| ID | Requisito | Tracciabilità |
|---|---|---|
| RF-040 | CRUD sistemi monitorati con `system_id`, endpoint heartbeat, intervallo, timeout, soglie, Probe, finestre di manutenzione. | UC-40..43 |
| RF-041 | La Probe deve interrogare periodicamente `GET /api/heartbeat` dei sistemi assegnati. | 01 §4, UC-41 |
| RF-042 | Il sistema deve registrare lo stato applicativo (`status`) e lo stato di connettività (raggiungibilità). | 01 §4.3 |
| RF-043 | Il sistema deve supportare heartbeat con più check per sistema (oggetto singolo o array). | 01 §4.2 |
| RF-044 | Consultazione dei check scoperti per sistema. | UC-44 |

### Persistenza serie temporali
| ID | Requisito | Tracciabilità |
|---|---|---|
| RF-050 | Ogni Probe deve archiviare gli heartbeat su OpenSearch locale. | 01 §5, 02 §5.1 |
| RF-051 | La serie temporale grezza non deve risiedere sul DB Server (solo rollup/snapshot). | 01 §7.2, DB doc |
| RF-052 | Le Probe devono applicare politiche di retention/rollover locali. | 02 §5.1 |

### Dashboard e consultazione
| ID | Requisito | Tracciabilità |
|---|---|---|
| RF-060 | Il Server deve fornire una dashboard aggregata di Probe e sistemi. | UC-50 |
| RF-061 | Il Server deve consentire di selezionare la Probe da consultare (drill-down). | UC-51 |
| RF-062 | Ogni Probe deve esporre una dashboard completa locale. | UC-52 |
| RF-063 | Il sistema deve consentire l'interrogazione diretta di OpenSearch (query filtrata). | UC-53 |
| RF-064 | Il sistema deve fornire grafici di serie temporali (latency, uptime, stati, eventi). | UC-54 |

### Notifiche e canali
| ID | Requisito | Tracciabilità |
|---|---|---|
| RF-070 | CRUD canali notifica per Email, Telegram, WhatsApp. | UC-60..62 |
| RF-071 | Test di invio su un canale. | UC-63 |
| RF-072 | Storico invii con esito. | UC-64 |
| RF-073 | Ogni canale, ove tecnicamente possibile, deve supportare la ricezione di comandi. | UC-80, UC-81, 07 doc |

### Workflow notifiche
| ID | Requisito | Tracciabilità |
|---|---|---|
| RF-080 | I workflow notifiche devono essere completamente configurabili (trigger, condizioni, azioni, escalation). | UC-70..72, 07 doc |
| RF-081 | Un invio di notifica deve avvenire solo tramite un workflow abilitato. | 01 §7.6 |
| RF-082 | I workflow devono supportare throttling/deduplica e finestre di manutenzione. | 07 doc |
| RF-083 | I workflow devono supportare escalation multi-step. | 07 doc |

### Comandi in ingresso
| ID | Requisito | Tracciabilità |
|---|---|---|
| RF-090 | Il sistema deve associare identità di canale a utenti Pulse. | UC-80 |
| RF-091 | L'esecuzione di comandi da canale deve rispettare i permessi RBAC dell'utente associato. | UC-81 |
| RF-092 | Il sistema deve documentare e applicare i limiti di fattibilità per canale. | 07 doc |

### Audit e log
| ID | Requisito | Tracciabilità |
|---|---|---|
| RF-100 | Ogni azione che modifica lo stato deve generare una voce di audit immutabile. | 01 §7.5, UC-90 |
| RF-101 | Consultazione filtrata dell'audit log. | UC-90 |
| RF-102 | Il sistema deve produrre log di sistema per Server e Probe. | UC-91 |
| RF-103 | Consultazione filtrata dei log di sistema. | UC-91 |

### Configurazione e comunicazione
| ID | Requisito | Tracciabilità |
|---|---|---|
| RF-110 | Il Server deve esporre endpoint dedicati alle Probe su una porta configurabile. | 02 §3, API |
| RF-111 | La comunicazione Server↔Probe deve essere cifrata e mutuamente autenticata. | 02 §4 |
| RF-112 | La configurazione (Server e Probe) deve essere gestibile. | UC-95, 02 §6 |
| RF-113 | Il sistema deve esporre endpoint di health/readiness per Server e Probe. | 01 §5.15, API |

---

## 2. Requisiti Non Funzionali (RNF)

### Sicurezza
| ID | Requisito |
|---|---|
| RNF-001 | Tutte le comunicazioni di rete (utente↔Server, Server↔Probe) devono usare TLS 1.2+ (preferito 1.3). |
| RNF-002 | La comunicazione Server↔Probe deve usare autenticazione mutua (mTLS) + token applicativo per-Probe, con revoca/rotazione. |
| RNF-003 | Le password devono essere memorizzate con algoritmo di hashing forte e salato. |
| RNF-004 | I segreti (SMTP, token bot, credenziali WhatsApp, chiavi Probe) devono essere cifrati a riposo o gestiti via secret store. |
| RNF-005 | L'accesso a ogni funzione deve essere autorizzato tramite RBAC (deny-by-default). |
| RNF-006 | L'audit log deve essere immutabile (append-only) e non alterabile via API applicative. |
| RNF-007 | I token di enrollment devono essere monouso e a scadenza. |

### Performance / Scalabilità
| ID | Requisito |
|---|---|
| RNF-010 | Una Probe deve sostenere il polling di almeno 100 sistemi (target) rispettando gli intervalli configurati. |
| RNF-011 | L'ingest su OpenSearch deve usare operazioni bulk per efficienza. |
| RNF-012 | La dashboard aggregata deve caricarsi da rollup senza fan-out sincrono verso tutte le Probe. |
| RNF-013 | Le query di consultazione devono supportare paginazione e filtri temporali. |
| RNF-014 | Il sistema deve supportare N Probe (scalabilità orizzontale per Probe). |

### Disponibilità / Affidabilità
| ID | Requisito |
|---|---|
| RNF-020 | Una Probe deve continuare a monitorare e archiviare localmente anche se il Server è irraggiungibile. |
| RNF-021 | Gli eventi/rollup non consegnati al Server devono essere ritentati (buffering/retry lato Probe). |
| RNF-022 | La perdita del Server non deve causare perdita di serie temporali (residenti sulle Probe). |
| RNF-023 | Gli invii di notifica falliti devono essere ritentati secondo policy configurabile. |

### Osservabilità
| ID | Requisito |
|---|---|
| RNF-030 | Log strutturati (JSON) con livello configurabile per Server e Probe. |
| RNF-031 | Endpoint health/readiness per orchestrazione container. |
| RNF-032 | Tracciabilità delle azioni tramite audit log correlato agli attori. |
| RNF-033 | Metriche operative di base visibili in dashboard (stato Probe, esiti polling, esiti notifiche). |

### Portabilità (Docker/Podman)
| ID | Requisito |
|---|---|
| RNF-040 | Le Probe devono essere eseguibili come container Docker e Podman senza modifiche. |
| RNF-041 | Devono essere forniti file compose equivalenti per Docker e Podman. |
| RNF-042 | Le immagini devono essere compatibili con esecuzione rootless. |
| RNF-043 | La configurazione deve essere iniettabile via variabili d'ambiente e volumi. |

### Manutenibilità / Coerenza
| ID | Requisito |
|---|---|
| RNF-050 | Nomi di entità, permessi ed endpoint devono essere coerenti tra tutti i documenti e il codice. |
| RNF-051 | Il DB Server deve essere agnostico dal motore a livello di modello logico. |
| RNF-052 | Le API devono esporre documentazione (OpenAPI) coerente con `DOCUMENTO_API.md`. |

### Usabilità / Localizzazione
| ID | Requisito |
|---|---|
| RNF-060 | La UI e la documentazione devono essere in italiano. |
| RNF-061 | I messaggi di errore devono essere chiari e non esporre dettagli sensibili. |

---

## 3. QUESTIONI APERTE / DECISIONI

| # | Tema | Decisione | Motivazione |
|---|---|---|---|
| RQ-01 | Target numerici (RNF-010) | Fissati valori target indicativi | I requisiti non danno numeri; valori da confermare per dimensionamento. |
| RQ-02 | Retention serie temporali | Configurabile per Probe, default da definire | Dipende da capacità disco/policy; scelta operativa. |
| RQ-03 | Alta disponibilità del Server | Non richiesta esplicitamente; singola istanza assunta | Nessun requisito HA; da valutare se necessario. |
