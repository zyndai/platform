# S12 explained with examples

S12 is the planned **“Request an intro”** feature: someone finds your Zynd card,
asks to connect with you, and you decide whether to accept.

This file explains the intended experience from the S12 convention. A human-only
implementation is now prepared locally, with feature flags off and shared
migrations unapplied. See [S12 intros](S12_INTROS.md) for what this release includes
and [manual testing](S12_MANUAL_TESTING.md) for examples to try. S09 code is present;
the live identity cutover still needs confirmation.

## Why do we need it?

Today, a profile card helps someone learn about you. S12 adds a next step:
asking for an introduction with a clear reason and a clear request.

For example, Bob discovers that Alice builds Python APIs. Instead of just reading
her card and leaving, he can ask:

> Hi Alice, I’m Bob. I’m building a developer tool and need advice about its API.
> Would you be open to a 20-minute call?

Alice can review that request before agreeing to connect or sharing anything.

## Example 1: Bob requests an intro and Alice accepts

Alice has claimed her card and has an active Persona agent linked to her account.
Her public card offers **Request intro**.

1. **Bob opens Alice's card.** He reads her profile and decides she might be a
   useful person to speak with.
2. **Bob signs in and requests an intro.** He explains who he is, why he wants
   to connect, and what he is asking for: a 20-minute call about Python APIs.
3. **Alice receives a pending request.** She can review it through Persona or
   the Cards owner home. The intended digest integration can also link her to it.
4. **Alice accepts with specific permissions.** For this example, she agrees
   to arrange a call but does not agree to share her email address.
5. **Persona helps propose meeting times.** With the required calendar access,
   it can find suitable slots. A proposed meeting still needs the relevant
   scheduling confirmations; accepting an intro is not the same as booking a meeting.

The result is a connection that Alice approved, with boundaries she agreed to.
Bob does not receive access to everything just because she accepted.

The simple flow is:

**Find card → Request intro → Owner reviews → Accept → Propose meeting times.**

## Example 2: Alice declines

Bob asks for an investment discussion, but Alice is not interested.

Alice declines the request. The request becomes declined, and the system does
not create an accepted connection, share new contact details, or arrange a call
through that request.

An intro request is a request for permission. Sending it does not grant permission.

## Example 3: Alice suggests another time

Bob asks for a call tomorrow. Alice is interested but is busy tomorrow.

She can suggest another time, such as next Tuesday. Persona helps coordinate
the proposal using the permissions and calendar access available.

The final scheduling details should remain clear to both people. Suggesting a
time should not silently book an event or expand what Alice agreed to share.

## Example 4: Bob's AI assistant asks on his behalf

Suppose Bob tells his assistant:

> Find someone experienced with Python APIs and help me request an introduction.

If the product decision allows agents to initiate intros, a verified assistant
could submit the request through the public Cards MCP action. MCP is the tool
interface an AI assistant uses to call Zynd features.

The assistant would still need an authenticated identity and the required
permissions. S09 supplies scoped assistant access and individual revocation;
S12 must enforce the permissions and applicable confirmation rules for intros.

For example, permission to read cards does not grant permission to send intro
requests. Permission to request an intro does not grant permission to accept
requests for Alice or access her calendar.

**Current decision:** The initial release allows signed-in humans to send and
decide requests. Assistants may read an owner's inbox with permission; agent
initiation and approval remain disabled. This example describes a possible later
extension, rather than the current release.

## What Cards and Persona each do

| Part | Role in S12 |
| --- | --- |
| Cards | Shows the profile and request form, checks eligibility, and displays intro status in the owner home. |
| Persona | Handles the connection, owner approval, granted permissions, and meeting coordination. |
| Memory/MCP | Lets authenticated assistants use permitted tools when agent initiation is enabled. |
| S10 owner home | Gives the owner another place to review requests and see intro activity. |

Cards should reuse Persona's connection machinery. Both interfaces should show
the same request and decision rather than maintaining two separate approvals.

The convention calls this **A2A**, meaning agent-to-agent communication. In plain
terms, the helpers behind the accounts coordinate the request while respecting
each person's identity, approval, and permissions.

## Examples of boundaries

- **An unclaimed card:** A scraped profile that Alice has never claimed should
  not offer or accept intro requests. Nobody should approve on her behalf.
- **No active Persona agent:** Even a claimed card needs an active linked agent
  before this intro action is offered.
- **A stranger pretending to be Bob:** Typing “I’m Bob” into the form is not
  proof of identity. The requester comes from the verified account or agent.
- **Repeated requests:** Daily limits per requester and per card, owner allow/deny
  lists, and protection against replaying requests help prevent spam. Exact
  limit values need to be chosen during implementation.
- **An assistant asks for extra access:** If Alice only approved coordinating a
  call, the assistant cannot use that approval to read private notes or share
  contact information she did not authorize.

The system should record request creation, decisions, and subsequent actions
so failures or misuse can be investigated. Intro-request and acceptance events
also make it possible to measure whether cards lead to connections.

## What else is needed if S09 is already complete?

S09 supplies assistant identity, scopes, and revocation. Full S12 also needs:

| Prerequisite | Why it matters |
| --- | --- |
| Persona auth audit | Confirm that only authorized users and services can create requests, make decisions, or access protected data. |
| Shared `zynd_uid` identity | Reliably link the same person's card, memory account, and Persona agent. Matching a display name is insufficient. |
| S11 public Cards MCP | Supplies the public assistant-facing surface whose intro action becomes live in S12. |
| Human/agent initiation decision | Defines who may send requests and which permissions and confirmations apply. |

S11 is needed for the full public MCP experience. A narrower web-only experience
could be scoped separately, but it would still need the auth and identity gates.

S12 is about turning **“I found your profile”** into **“I asked to connect, you
approved, and we can now coordinate within the permissions you granted.”**
