# Zynd AI — Neural Mesh Design System
> Paste this entire document into your AI coding assistant as context before implementing any UI component.

---

## Concept

**Bloomberg Terminal × Web3 Wallet.**
Dark, data-dense, cryptographically trusted — but warm enough for real human networking. Not another purple-gradient crypto app. Not a bland SaaS dashboard.

The personality: a professional who works in DeFi, reads terminal data, and still sends thoughtful DMs.

---

## Typography

Use these three Google Fonts. Import them together:

```html
<link href="https://fonts.googleapis.com/css2?family=Syne:wght@400;500;600;700;800&family=IBM+Plex+Mono:wght@300;400;500&family=DM+Sans:ital,opsz,wght@0,9..40,300;0,9..40,400;0,9..40,500;1,9..40,300&display=swap" rel="stylesheet">
```

| Role | Font | Weight | Usage |
|------|------|--------|-------|
| Display / Wordmark | Syne | 800 | Logo, page titles, hero text |
| Heading | Syne | 600–700 | Section headings, card titles |
| Body | DM Sans | 400 | All conversational text, descriptions, messages |
| Body emphasis | DM Sans | 500 | Names, labels, important UI text |
| Data / Mono | IBM Plex Mono | 400–500 | DID strings, wallet addresses, timestamps, status labels, section labels in ALL CAPS |

**Rules:**
- Section labels (e.g. "ACTIVE CONTACTS", "NETWORK STATUS"): `IBM Plex Mono`, `font-size: 10px`, `letter-spacing: 1.5px`, `text-transform: uppercase`, color `var(--text-muted)`
- Never use Inter, Roboto, or system fonts
- Never use font-weight 600+ for DM Sans (it goes heavy fast)

---

## Color System

Define these as CSS custom properties on `:root`:

```css
:root {
  /* Background layers — use in order from outermost to innermost */
  --bg-void:      #080A0F;  /* page/outermost background */
  --bg-base:      #0D1117;  /* main panels, sidebar */
  --bg-surface:   #131921;  /* cards, input fields, nav items */
  --bg-raised:    #1A2332;  /* hover states, elevated cards */
  --bg-overlay:   #1E2A3D;  /* tooltips, dropdowns */

  /* Accent colors — each carries semantic meaning */
  --accent-teal:   #00D4B4;  /* primary: trust, network activity, success */
  --accent-blue:   #4F8EF7;  /* data, connections, info, automated pings */
  --accent-amber:  #F0A500;  /* identity, alerts, warnings */
  --accent-coral:  #FF5F6D;  /* danger, delete, error */
  --accent-purple: #8B5CF6;  /* AI intelligence, smart actions */

  /* Glow effects — use sparingly, only on active/focus states */
  --glow-teal:  0 0 20px rgba(0, 212, 180, 0.18);
  --glow-blue:  0 0 20px rgba(79, 142, 247, 0.15);

  /* Text */
  --text-primary:   #E8EDF5;  /* main readable text */
  --text-secondary: #8A96A8;  /* supporting text, descriptions */
  --text-muted:     #4A5568;  /* labels, placeholders, meta info */

  /* Borders */
  --border-subtle:  rgba(255, 255, 255, 0.05);  /* between sections */
  --border-default: rgba(255, 255, 255, 0.09);  /* cards, inputs */
  --border-strong:  rgba(0, 212, 180, 0.30);    /* focused/active elements */

  /* Border radius scale */
  --r-sm: 6px;
  --r-md: 10px;
  --r-lg: 16px;
  --r-xl: 24px;
}
```

### Semantic Color Mapping

| Color | When to use |
|-------|-------------|
| `--accent-teal` | Primary actions, send button, active nav, verified badges, success states, network pings |
| `--accent-blue` | Data display, connection info, automated agent messages, secondary actions |
| `--accent-amber` | DID/identity blocks, pending states, warnings |
| `--accent-coral` | Delete, revoke, error, destructive actions |
| `--accent-purple` | AI-generated content, smart suggestions, agent status |

---

## Background Texture

Apply a subtle grid to the outermost page container to reinforce the "terminal" feel:

```css
.page-bg::before {
  content: '';
  position: fixed;
  inset: 0;
  background-image:
    linear-gradient(rgba(0, 212, 180, 0.015) 1px, transparent 1px),
    linear-gradient(90deg, rgba(0, 212, 180, 0.015) 1px, transparent 1px);
  background-size: 40px 40px;
  pointer-events: none;
  z-index: 0;
}
```

---

## Layout

### App Shell (3-column)

```
┌─────────────┬──────────────────────────────┬──────────────┐
│  Sidebar    │        Main Content           │  Right Panel │
│  220px      │        flex: 1               │  300px       │
│  --bg-base  │        --bg-base             │  --bg-base   │
└─────────────┴──────────────────────────────┴──────────────┘
```

- All three columns separated by `1px solid var(--border-subtle)`
- Sidebar has a decorative gradient right-border accent (see Sidebar section)
- Topbar: `height: 56px`, `background: rgba(13,17,23,0.9)`, `backdrop-filter: blur(8px)`

---

## Components

### Sidebar

```css
.sidebar {
  width: 220px;
  background: var(--bg-base);
  border-right: 1px solid var(--border-subtle);
  position: relative;
}

/* Animated accent line on right edge */
.sidebar::after {
  content: '';
  position: absolute;
  top: 0; right: -1px;
  width: 1px; height: 100%;
  background: linear-gradient(180deg,
    transparent,
    var(--accent-teal) 40%,
    var(--accent-blue) 70%,
    transparent
  );
  opacity: 0.4;
}
```

**Wordmark:**
- Logo square: `30×30px`, `border-radius: var(--r-sm)`, gradient `135deg` from `--accent-teal` to `--accent-blue`, `font-family: Syne`, `font-weight: 800`, text color `--bg-void`
- App name: `Syne 700`, `font-size: 16px`, `letter-spacing: 0.5px` — accent the "AI" part in `--accent-teal`

**Nav items:**

```css
.nav-item {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 9px 12px;
  border-radius: var(--r-md);
  font-size: 13.5px;
  color: var(--text-secondary);
  border: 1px solid transparent;
  transition: all 0.15s ease;
}

.nav-item:hover {
  background: rgba(255, 255, 255, 0.04);
  color: var(--text-primary);
  border-color: var(--border-subtle);
}

.nav-item.active {
  background: rgba(0, 212, 180, 0.08);
  color: var(--accent-teal);
  border-color: rgba(0, 212, 180, 0.20);
}

/* Left accent bar on active item */
.nav-item.active::before {
  content: '';
  position: absolute;
  left: -10px; top: 50%;
  transform: translateY(-50%);
  width: 3px; height: 16px;
  background: var(--accent-teal);
  border-radius: 0 2px 2px 0;
  box-shadow: var(--glow-teal);
}
```

**Nav badges** (unread counts):
```css
.nav-badge {
  margin-left: auto;
  background: var(--accent-teal);
  color: var(--bg-void);
  font-size: 10px;
  font-weight: 700;
  font-family: IBM Plex Mono;
  padding: 1px 6px;
  border-radius: 20px;
}
```

**User card (sidebar footer):**
- Avatar: `32×32px`, circular, gradient `135deg` from `--accent-blue` to `--accent-purple`, initials in Syne 700
- Online dot: `8×8px` circle, `--accent-teal`, positioned bottom-right of avatar, `border: 2px solid var(--bg-base)`
- DID: `IBM Plex Mono 9.5px`, `--text-muted`, truncate with ellipsis

---

### Status Pill

Used in topbar and wherever agent/network status is shown:

```css
.status-pill {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 4px 10px;
  background: rgba(0, 212, 180, 0.08);
  border: 1px solid rgba(0, 212, 180, 0.20);
  border-radius: 20px;
  font-size: 11px;
  font-family: IBM Plex Mono;
  color: var(--accent-teal);
}

/* Pulsing dot inside pill */
.status-dot {
  width: 6px; height: 6px;
  background: var(--accent-teal);
  border-radius: 50%;
  animation: pulse 2s ease infinite;
}

@keyframes pulse {
  0%, 100% { opacity: 1; transform: scale(1); }
  50%       { opacity: 0.5; transform: scale(0.8); }
}
```

---

### Chat Messages

**AI agent message:**
```css
.msg-ai {
  display: flex;
  gap: 12px;
  max-width: 75%;
  align-self: flex-start;
  animation: slideIn 0.2s ease;
}

.msg-bubble-ai {
  background: var(--bg-surface);
  border: 1px solid var(--border-default);
  border-radius: 4px var(--r-lg) var(--r-lg) var(--r-lg);
  padding: 14px 16px;
  font-size: 14px;
  line-height: 1.65;
  color: var(--text-primary);
  position: relative;
}

/* Teal gradient top edge — signals AI origin */
.msg-bubble-ai::before {
  content: '';
  position: absolute;
  top: 0; left: 0; right: 0;
  height: 1px;
  background: linear-gradient(90deg, var(--accent-teal), transparent 60%);
  border-radius: 4px 4px 0 0;
  opacity: 0.5;
}
```

**User message:**
```css
.msg-bubble-user {
  background: linear-gradient(135deg,
    rgba(0, 212, 180, 0.15),
    rgba(79, 142, 247, 0.12)
  );
  border: 1px solid rgba(0, 212, 180, 0.25);
  border-radius: var(--r-lg) 4px var(--r-lg) var(--r-lg);
  padding: 12px 16px;
  font-size: 14px;
  line-height: 1.6;
  color: var(--text-primary);
  align-self: flex-end;
}
```

**Automated Ping message** (agent-to-agent on network):
```css
.msg-bubble-ping {
  background: rgba(79, 142, 247, 0.06);
  border: 1px solid rgba(79, 142, 247, 0.15);
  border-radius: 4px var(--r-lg) var(--r-lg) var(--r-lg);
  padding: 12px 16px;
  font-size: 13.5px;
  color: var(--text-secondary);
}
```

Ping tag label (shown above ping message text):
```css
.ping-tag {
  font-family: IBM Plex Mono;
  font-size: 10px;
  font-weight: 500;
  color: var(--accent-blue);
  background: rgba(79, 142, 247, 0.12);
  padding: 2px 7px;
  border-radius: 4px;
  border: 1px solid rgba(79, 142, 247, 0.20);
  display: inline-block;
  margin-bottom: 6px;
}
```

**Message appear animation:**
```css
@keyframes slideIn {
  from { opacity: 0; transform: translateY(8px); }
  to   { opacity: 1; transform: translateY(0); }
}
```

**AI avatar** (shown left of AI messages): `32×32px`, `border-radius: var(--r-sm)`, gradient teal→blue, Syne 800 "Z", color `--bg-void`

**Timestamp:** `IBM Plex Mono 10px`, `--text-muted`

---

### Input Bar

```css
.input-wrap {
  display: flex;
  align-items: center;
  gap: 10px;
  background: var(--bg-surface);
  border: 1px solid var(--border-default);
  border-radius: var(--r-lg);
  padding: 10px 14px;
  transition: border-color 0.15s ease;
}

.input-wrap:focus-within {
  border-color: rgba(0, 212, 180, 0.40);
  box-shadow: var(--glow-teal);
}

input.chat-input {
  flex: 1;
  background: none;
  border: none;
  outline: none;
  color: var(--text-primary);
  font-family: DM Sans;
  font-size: 14px;
}

input.chat-input::placeholder {
  color: var(--text-muted);
}
```

---

### Buttons

```css
/* Primary — main CTA, send */
.btn-primary {
  padding: 10px 20px;
  background: var(--accent-teal);
  border: none;
  border-radius: var(--r-md);
  font-family: Syne;
  font-size: 13px;
  font-weight: 600;
  color: var(--bg-void);
  cursor: pointer;
  transition: all 0.15s ease;
}
.btn-primary:hover {
  filter: brightness(1.1);
  transform: translateY(-1px);
  box-shadow: var(--glow-teal);
}
.btn-primary:active { transform: translateY(0); }

/* Secondary — outline style */
.btn-secondary {
  padding: 10px 20px;
  background: transparent;
  border: 1px solid var(--border-default);
  border-radius: var(--r-md);
  font-family: Syne;
  font-size: 13px;
  font-weight: 500;
  color: var(--text-secondary);
  cursor: pointer;
  transition: all 0.15s;
}
.btn-secondary:hover {
  border-color: var(--accent-teal);
  color: var(--accent-teal);
}

/* Ghost — tinted, for secondary Web3 actions */
.btn-ghost-blue {
  padding: 10px 20px;
  background: rgba(79, 142, 247, 0.10);
  border: 1px solid rgba(79, 142, 247, 0.25);
  border-radius: var(--r-md);
  font-family: Syne;
  font-size: 13px;
  font-weight: 500;
  color: var(--accent-blue);
  cursor: pointer;
  transition: all 0.15s;
}
.btn-ghost-blue:hover { background: rgba(79, 142, 247, 0.18); }

/* Danger — destructive actions */
.btn-danger {
  padding: 10px 20px;
  background: rgba(255, 95, 109, 0.10);
  border: 1px solid rgba(255, 95, 109, 0.25);
  border-radius: var(--r-md);
  font-family: Syne;
  font-size: 13px;
  font-weight: 500;
  color: var(--accent-coral);
  cursor: pointer;
  transition: all 0.15s;
}
```

---

### Tags / Badges

```css
/* Base tag */
.tag {
  font-size: 10.5px;
  font-family: IBM Plex Mono;
  padding: 2px 8px;
  border-radius: 4px;
  border: 1px solid;
  display: inline-flex;
  align-items: center;
}

.tag-teal   { background: rgba(0, 212, 180, 0.08); border-color: rgba(0, 212, 180, 0.20); color: var(--accent-teal); }
.tag-blue   { background: rgba(79, 142, 247, 0.08); border-color: rgba(79, 142, 247, 0.20); color: var(--accent-blue); }
.tag-amber  { background: rgba(240, 165, 0, 0.08);  border-color: rgba(240, 165, 0, 0.20);  color: var(--accent-amber); }
.tag-coral  { background: rgba(255, 95, 109, 0.08); border-color: rgba(255, 95, 109, 0.20); color: var(--accent-coral); }
.tag-purple { background: rgba(139, 92, 246, 0.08); border-color: rgba(139, 92, 246, 0.20); color: var(--accent-purple); }
```

---

### Cards (Contact / Content)

```css
.card {
  background: var(--bg-surface);
  border: 1px solid var(--border-default);
  border-radius: var(--r-md);
  padding: 14px;
  cursor: pointer;
  transition: all 0.15s;
  position: relative;
  overflow: hidden;
}

/* Left accent bar — appears on hover */
.card::before {
  content: '';
  position: absolute;
  top: 0; left: 0;
  width: 3px; height: 100%;
  background: var(--accent-teal);
  opacity: 0;
  transition: opacity 0.15s;
}

.card:hover {
  border-color: var(--border-strong);
  background: var(--bg-raised);
}

.card:hover::before { opacity: 1; }
```

---

### Stat / Metric Boxes

Small 2-column grid for numeric stats (message count, connection count, etc.):

```css
.stat-box {
  background: var(--bg-surface);
  border: 1px solid var(--border-subtle);
  border-radius: var(--r-md);
  padding: 12px;
}

.stat-label {
  font-size: 9.5px;
  font-family: IBM Plex Mono;
  font-weight: 500;
  letter-spacing: 0.8px;
  color: var(--text-muted);
  text-transform: uppercase;
  margin-bottom: 5px;
}

.stat-value {
  font-family: Syne;
  font-size: 20px;
  font-weight: 700;
  color: var(--text-primary);
  line-height: 1;
}

.stat-delta {
  font-size: 10.5px;
  color: var(--accent-teal);
  font-family: IBM Plex Mono;
  margin-top: 3px;
}
```

---

### Identity / DID Block

For displaying decentralized identifiers:

```css
.identity-block {
  background: var(--bg-surface);
  border: 1px solid var(--border-default);
  border-radius: var(--r-md);
  padding: 12px 14px;
}

.did-string {
  font-family: IBM Plex Mono;
  font-size: 10.5px;
  color: var(--accent-teal);
  word-break: break-all;
  line-height: 1.5;
  opacity: 0.8;
}

.verified-badge {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  margin-top: 8px;
  font-size: 10px;
  font-family: IBM Plex Mono;
  color: var(--accent-teal);
  background: rgba(0, 212, 180, 0.08);
  border: 1px solid rgba(0, 212, 180, 0.20);
  padding: 3px 8px;
  border-radius: 4px;
}
```

---

### Progress / Chain Indicators

Progress bar:
```css
.progress-track {
  background: var(--bg-surface);
  border-radius: 20px;
  height: 4px;
  overflow: hidden;
}

.progress-fill {
  height: 100%;
  background: linear-gradient(90deg, var(--accent-teal), var(--accent-blue));
  border-radius: 20px;
}
```

Network chain display (e.g. Mumbai → Amoy → Mainnet):
```css
.chain-node {
  background: var(--bg-surface);
  border: 1px solid var(--border-default);
  border-radius: var(--r-sm);
  padding: 4px 10px;
  font-family: IBM Plex Mono;
  font-size: 11px;
  color: var(--text-secondary);
}

.chain-node.active {
  border-color: rgba(0, 212, 180, 0.40);
  color: var(--accent-teal);
  background: rgba(0, 212, 180, 0.06);
}

.chain-line {
  flex: 1;
  height: 1px;
  background: linear-gradient(90deg, var(--border-default), var(--accent-teal), var(--border-default));
}
```

---

## Motion Rules

| Interaction | Value |
|-------------|-------|
| Default transition | `all 0.15s ease` |
| Message appear | `slideIn 0.2s ease` — `opacity: 0 → 1`, `translateY(8px → 0)` |
| Button hover lift | `translateY(-1px)` |
| Button active press | `translateY(0)` |
| Status dot pulse | `2s ease infinite` — scale 1→0.8, opacity 1→0.5 |
| Focus glow | `box-shadow: var(--glow-teal)` on `:focus-within` |

---

## Spacing & Radius Scale

```
--r-sm: 6px   → small buttons, tags, inner controls
--r-md: 10px  → nav items, cards, inputs, stat boxes
--r-lg: 16px  → message bubbles, main cards, input bar
--r-xl: 24px  → modal overlays, large panels

Spacing: 4 / 8 / 12 / 16 / 20 / 24 / 32 / 48px
```

---

## Do / Don't

**Do:**
- Use `IBM Plex Mono` for any string that looks like data (addresses, timestamps, IDs, network labels)
- Apply the left-border accent (`::before` trick) for any clickable list item to show hover
- Use tinted ghost backgrounds for secondary actions (`rgba(accent, 0.08)` fill, `rgba(accent, 0.20)` border)
- Layer backgrounds: page=void → panels=base → cards=surface → hover=raised
- Show the `--accent-teal` glow only on focus/active states, never decoratively

**Don't:**
- Use gradients on card backgrounds (flat surfaces only — gradients are reserved for the wordmark logo and progress fills)
- Use more than 2 accent colors in one component
- Apply `var(--accent-teal)` to text unless it's a data string, link, or verified label
- Use font-weight above 600 in DM Sans
- Use rounded pills (`border-radius: 20px`) for anything except status pills and nav badges

---

## Quick Reference: CSS Variables Cheatsheet

```css
/* Most-used vars */
--bg-surface     /* default card background */
--bg-raised      /* hover state background */
--border-default /* standard 1px card border */
--border-strong  /* active/focused teal border */
--accent-teal    /* primary accent — trust, action */
--accent-blue    /* data, connections, info */
--text-primary   /* readable body text */
--text-muted     /* labels, placeholders */
--r-md           /* 10px — standard radius */
--r-lg           /* 16px — message bubbles, large cards */
--glow-teal      /* box-shadow for focused inputs/buttons */
```