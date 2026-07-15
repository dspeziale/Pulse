# Pulse — Modello RBAC

Documento: `06_rbac.md`
Autore: AGENTE 1 — ANALISTA
Data: 2026-07-15

Questo documento è la **fonte di verità dei permessi**. I codici permesso qui definiti sono usati identici in `docs/api/DOCUMENTO_API.md`, nei casi d'uso e nel modello dati.

---

## 1. Modello

- **Utente** ↔ N **Ruoli** (relazione molti-a-molti).
- **Ruolo** ↔ N **Permessi** (relazione molti-a-molti).
- I permessi dell'utente sono l'**unione** dei permessi dei suoi ruoli.
- Principio **deny-by-default**: senza permesso esplicito l'operazione è negata.
- Il **catalogo permessi è fisso** (definito dal sistema, non creabile a runtime).
- I **ruoli predefiniti** non sono eliminabili né modificabili nella struttura; sono creabili ruoli personalizzati.

Formato codice permesso: `area.azione`.

---

## 2. Catalogo permessi (granulari)

### Profilo personale
| Codice | Descrizione |
|---|---|
| `profile.read` | Leggere il proprio profilo. |
| `profile.update` | Aggiornare il proprio profilo / cambiare la propria password. |

> Nota: login/refresh/logout non richiedono permesso (sono operazioni di autenticazione). `profile.*` è implicitamente concesso a ogni utente autenticato ma è elencato per completezza e per la UI.

### Utenti
| Codice | Descrizione |
|---|---|
| `users.read` | Elencare/consultare utenti. |
| `users.create` | Creare utenti. |
| `users.update` | Modificare utenti, stato, reset password. |
| `users.delete` | Eliminare/disabilitare utenti. |
| `users.assign_roles` | Assegnare/rimuovere ruoli agli utenti. |

### Ruoli
| Codice | Descrizione |
|---|---|
| `roles.read` | Consultare ruoli. |
| `roles.create` | Creare ruoli. |
| `roles.update` | Modificare ruoli. |
| `roles.delete` | Eliminare ruoli. |
| `roles.assign_permissions` | Assegnare permessi ai ruoli. |

### Permessi
| Codice | Descrizione |
|---|---|
| `permissions.read` | Consultare il catalogo permessi. |

### Probe (Sonde)
| Codice | Descrizione |
|---|---|
| `probes.read` | Consultare Probe e stato. |
| `probes.create` | Registrare/enrollare Probe. |
| `probes.update` | Modificare definizione Probe. |
| `probes.delete` | Eliminare Probe. |
| `probes.rotate_key` | Ruotare/revocare credenziali/certificato Probe. |

### Sistemi monitorati
| Codice | Descrizione |
|---|---|
| `systems.read` | Consultare sistemi monitorati. |
| `systems.create` | Creare sistemi monitorati. |
| `systems.update` | Modificare sistemi monitorati. |
| `systems.delete` | Eliminare sistemi monitorati. |

### Check
| Codice | Descrizione |
|---|---|
| `checks.read` | Consultare i check scoperti dei sistemi. |

### Heartbeat / Query / Dashboard
| Codice | Descrizione |
|---|---|
| `dashboard.read` | Accedere alle dashboard (aggregata Server e Probe). |
| `heartbeats.read` | Leggere serie temporali/heartbeat (drill-down, grafici). |
| `heartbeats.query` | Eseguire interrogazioni dirette/avanzate su OpenSearch. |

### Notifiche / Canali
| Codice | Descrizione |
|---|---|
| `notifications.read` | Consultare canali e storico invii. |
| `notifications.create` | Creare canali notifica. |
| `notifications.update` | Modificare canali notifica. |
| `notifications.delete` | Eliminare canali notifica. |
| `notifications.test` | Inviare messaggi di test su un canale. |

### Workflow notifiche
| Codice | Descrizione |
|---|---|
| `workflows.read` | Consultare workflow. |
| `workflows.create` | Creare workflow. |
| `workflows.update` | Modificare/abilitare/disabilitare workflow. |
| `workflows.delete` | Eliminare workflow. |

### Comandi in ingresso
| Codice | Descrizione |
|---|---|
| `commands.execute` | Associare la propria identità di canale ed eseguire comandi consentiti dai canali. |

### Audit
| Codice | Descrizione |
|---|---|
| `audit.read` | Consultare l'audit log. |

### Log di sistema
| Codice | Descrizione |
|---|---|
| `syslog.read` | Consultare i log di sistema. |

### Configurazione
| Codice | Descrizione |
|---|---|
| `config.read` | Consultare la configurazione. |
| `config.update` | Modificare la configurazione. |

Totale: **37 permessi** (di cui 2 di profilo impliciti).

---

## 3. Ruoli predefiniti

| Ruolo | Descrizione | Eliminabile |
|---|---|---|
| **SuperAdmin** | Controllo totale, inclusa gestione ruoli/permessi e degli altri amministratori. | No |
| **Admin** | Gestione operativa completa (probe, sistemi, notifiche, workflow, config) e gestione utenti; non gestisce la struttura di ruoli/permessi. | No |
| **Operator** | Operatività su probe/sistemi/notifiche/workflow, consultazione, esecuzione comandi. Nessuna gestione utenti/ruoli/config. | No |
| **Viewer** | Sola consultazione (dashboard, heartbeat, sistemi, probe). | No |
| **Auditor** | Sola consultazione di audit log e log di sistema (+ dashboard base). | No |

---

## 4. Matrice Ruoli × Permessi

Legenda: ✔ = concesso, vuoto = non concesso.

| Permesso | SuperAdmin | Admin | Operator | Viewer | Auditor |
|---|:--:|:--:|:--:|:--:|:--:|
| profile.read | ✔ | ✔ | ✔ | ✔ | ✔ |
| profile.update | ✔ | ✔ | ✔ | ✔ | ✔ |
| users.read | ✔ | ✔ | | | |
| users.create | ✔ | ✔ | | | |
| users.update | ✔ | ✔ | | | |
| users.delete | ✔ | ✔ | | | |
| users.assign_roles | ✔ | ✔ | | | |
| roles.read | ✔ | ✔ | | | |
| roles.create | ✔ | | | | |
| roles.update | ✔ | | | | |
| roles.delete | ✔ | | | | |
| roles.assign_permissions | ✔ | | | | |
| permissions.read | ✔ | ✔ | | | |
| probes.read | ✔ | ✔ | ✔ | ✔ | |
| probes.create | ✔ | ✔ | | | |
| probes.update | ✔ | ✔ | ✔ | | |
| probes.delete | ✔ | ✔ | | | |
| probes.rotate_key | ✔ | ✔ | | | |
| systems.read | ✔ | ✔ | ✔ | ✔ | |
| systems.create | ✔ | ✔ | ✔ | | |
| systems.update | ✔ | ✔ | ✔ | | |
| systems.delete | ✔ | ✔ | | | |
| checks.read | ✔ | ✔ | ✔ | ✔ | |
| dashboard.read | ✔ | ✔ | ✔ | ✔ | ✔ |
| heartbeats.read | ✔ | ✔ | ✔ | ✔ | |
| heartbeats.query | ✔ | ✔ | ✔ | | |
| notifications.read | ✔ | ✔ | ✔ | | |
| notifications.create | ✔ | ✔ | ✔ | | |
| notifications.update | ✔ | ✔ | ✔ | | |
| notifications.delete | ✔ | ✔ | | | |
| notifications.test | ✔ | ✔ | ✔ | | |
| workflows.read | ✔ | ✔ | ✔ | | |
| workflows.create | ✔ | ✔ | ✔ | | |
| workflows.update | ✔ | ✔ | ✔ | | |
| workflows.delete | ✔ | ✔ | | | |
| commands.execute | ✔ | ✔ | ✔ | | |
| audit.read | ✔ | ✔ | | | ✔ |
| syslog.read | ✔ | ✔ | | | ✔ |
| config.read | ✔ | ✔ | | | |
| config.update | ✔ | ✔ | | | |

---

## 5. Regole di integrità RBAC

1. Deve sempre esistere ≥1 utente attivo con ruolo **SuperAdmin** (RF-021).
2. Un utente non può auto-eliminarsi né auto-disabilitarsi.
3. I ruoli predefiniti non sono eliminabili; i loro permessi non sono modificabili (per garantire coerenza operativa). I ruoli **personalizzati** sono pienamente configurabili.
4. La revoca di un permesso da un ruolo ha effetto immediato sulle richieste successive degli utenti di quel ruolo.
5. L'autenticazione della **Probe** (attore di sistema) è indipendente dal RBAC utente: usa credenziali per-Probe (mTLS + token) e ha accesso solo agli endpoint dedicati (`/api/v1/probe/*` in ingest e alla propria configurazione), non alle API di gestione.

---

## 6. QUESTIONI APERTE / DECISIONI

| # | Tema | Decisione | Motivazione |
|---|---|---|---|
| RB-01 | Distinzione SuperAdmin/Admin | SuperAdmin gestisce ruoli/permessi; Admin gestisce operatività + utenti | Separazione dei privilegi: la modifica della struttura di autorizzazione è più sensibile. |
| RB-02 | Ruoli predefiniti modificabili? | No (struttura bloccata), sì ruoli personalizzati | Evita di indebolire per errore ruoli critici; flessibilità via ruoli custom. |
| RB-03 | Permessi scoping per-Probe/per-sistema (row-level) | Non incluso (permessi globali per area) | I requisiti non richiedono scoping fine; da valutare se emergesse la necessità di multi-tenant. |
