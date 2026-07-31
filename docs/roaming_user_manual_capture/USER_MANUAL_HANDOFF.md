# Roaming Recommender User Manual Handoff

## Purpose and capture basis

This handoff documents the customer-facing **Roaming Recommender** exactly as it behaved on 30 July 2026. It is intended as source material for a formal User Manual, not as an architecture or setup guide.

- Walkthrough account: seeded Aisha account (`aisha@example.test`). The password is intentionally omitted.
- Primary capture: mobile/PWA layout at `430 × 900` CSS pixels.
- Desktop reference: Phone mode at `432 × 886`; Expanded mode at `1040 × 920`.
- Destination: France.
- Main seven-day trip: 29 August–4 September 2026, inclusive.
- Separate three-day split-request trip: 12–14 September 2026, inclusive.
- Desktop trip: 4–10 August 2026, inclusive.
- The normal Waitress-served Flask application, current SQLite data, session workflow, and real recommendation endpoints were used. Gemini connection attempts were unavailable during this capture, so the application followed its implemented deterministic fallback/Smart History paths. No UI was fabricated.
- All customer, account, usage, package, price, and activation-code values shown are seeded POC data.

## Customer workflow at a glance

1. Sign in and open **Roaming** from the dashboard or bottom navigation.
2. On **Roaming Recommender**, select **Start planning**.
3. Choose a destination in **Step 1 of 4 – Destination**, then select **Continue**.
4. Enter **Departure** and **Return** dates in **Step 2 of 4 – Travel dates**, then select **Continue**.
5. Wait while **Finding your best fit** completes.
6. Review the plan in **Step 3 of 4 – Review and adjust**. Open **More details** or use **Adjust recommendation** if needed.
7. Select **Continue with this plan**.
8. On **Step 4 of 4 – Final recommendation**, review the complete sequence and confirm the preferred-partner acknowledgement.
9. Use **Copy activation codes** and **Open code in dialer** for a single activation, or **Open first code in dialer** when the plan contains multiple activations, only after reviewing the activation guidance. Nothing is activated automatically.
10. Optionally select **Save Selection**, then select **Done**, **Start New**, or **Home**.

## Detailed customer instructions

### A. Access

- Authentication is required. The sign-in fields are **Email or phone** and **Password**; the action is **Sign in**.
- From the authenticated home screen, the roaming entry appears as the Roaming dashboard card and as **Roaming** in the bottom navigation.
- The authenticated bottom navigation is **Home**, **Insights**, **Support**, **Roaming**, and **Profile**.
- The global back arrow above the roaming title returns to the prior application area. The workflow-specific arrows, **Back**, and **Exit** are described below.

### B. Roaming landing page

- Page title: **Roaming Recommender**.
- Intro heading: **Where will your next trip take you?**
- Instruction: **Choose a destination and travel dates to find a package that fits.**
- **Start planning** opens Step 1. If the current journey is already completed, starting again clears that completed draft first.
- Before a journey exists, **RECENT RECOMMENDATION** shows **No recent trip yet** and **Complete a recommendation to see it here.**
- After completion, the recent card shows destination, trip length, package name, and price; its chevron opens that recommendation.
- Session-saved plans appear under **Saved Recommendations**. Each card shows package name(s), destination, dates, total price, total data, and activation count, with **View Details** and **Remove**.
- **View Details** opens the saved final recommendation. **Remove** opens a confirmation sheet before deletion.
- **Start New** is on the final recommendation, not the initial landing page. It clears the roaming draft and opens a fresh destination screen.

### C. Step 1 – Destination

- Heading: **Choose your destination**. The UI states: **Travelling from the UAE is already assumed.**
- **Search countries** performs case-insensitive prefix matching against the country name. It does not search country codes or arbitrary letters within a name.
- Example: entering `B` showed only Bahrain, Belgium, and Brazil. Saudi Arabia did not appear.
- The current catalogue displayed 32 supported countries, grouped under **DESTINATIONS A–Z**, one country per row.
- Selecting a country adds a check mark and enables **Continue**. Selecting a different country clears any recommendation tied to the previous destination.
- Only the country-results region scrolls in the mobile layout; the primary action remains at the bottom of the step.
- With no match, the count becomes **0 countries** and the message is **No countries begin with that search. Try another name.** **Continue** remains disabled.
- The workflow arrow returns to the roaming landing page. **Exit** also returns to the landing page without acting as **Start New**.

### D. Step 2 – Travel dates

- The selected country remains visible with an **Edit** control.
- Both **Departure** and **Return** are required date inputs. The browser date controls are limited to the next calendar day or later.
- Duration is inclusive: departure on 29 August and return on 4 September displays **7 days**.
- Return cannot precede departure. The message is **Return date must be on or after the departure date.**
- Past dates are rejected with **Choose travel dates in the future.**
- **Continue** stays disabled until a valid pair produces a trip duration.
- **Back**, the workflow arrow, and **Edit** return to Step 1 while retaining the selected country. **Exit** returns to the roaming landing page.

### E. Analysis/loading

- The loading heading is **Finding your best fit**.
- The four visible phases are, in order:
  1. **Checking destination coverage**
  2. **Analysing recent usage**
  3. **Comparing all active packages**
  4. **Validating the recommendation**
- The loading screen also shows the labels **Destination**, **Duration**, **Usage**, and **Value**.
- If recommendation loading fails, the UI returns to Travel dates and displays the returned plain-language error as a toast. Relevant messages include **The package catalogue is temporarily unavailable.** and package-availability/validation text returned by the backend.

### F. Step 3 – Recommendation

The screen is labelled **Step 3 of 4 – Review and adjust**. The current plan card displays:

- **BASED ON CURRENT USAGE** and **Recommended** status labels.
- Package order, package family/name, quantity when greater than one, coverage days, and per-package price.
- Per-package data, local minutes, international minutes, and SMS.
- Total price in AED, destination, trip length, and combined validity.
- Combined data, **Local / roaming**, **International**, SMS, and activation count.
- A segment timeline only when the backend returns segment data.
- **More details** / **Hide details**.
- **Your Average Usage in _n_ Days**, with data, local minutes, international minutes, and SMS scaled from recent usage.
- **Why this fits** and the backend’s short fit statements.
- **Adjust recommendation** chat and **Continue with this plan**.

Observed initial seven-day result:

| Field | Value |
|---|---|
| Package | Roam Essentials 7 Days |
| Coverage | Days 1–7 |
| Price | AED 69 |
| Combined validity | 7 days |
| Data | 3.0 GB |
| Local / roaming | 100 min |
| International | 35 min |
| SMS | 30 |
| Activations | 1 |
| Scaled usage | 1.0 GB, 27 local min, 5 international min, 3 SMS |

### G. Adjust recommendation chat

- Placeholder: **For example: I need more data, fewer calls, or a lower price…**
- The visible send control is an up-arrow with the accessible name **Send adjustment**. It is disabled until non-whitespace text is entered.
- Selecting the send arrow or pressing Enter sends the message. Shift+Enter retains the textarea’s normal newline behavior.
- While waiting, the assistant message is **Reviewing that adjustment…**
- A completed adjustment updates the current recommendation, scrolls the recommendation card into view, and shows **Recommendation reviewed.** Restoring history shows **Recommendation restored.**
- Refinements are cumulative: each request is interpreted against the latest selected plan and its complete current requirements, not only the first plan.
- An exact request sets minimum requirements. Unmentioned services are intended to remain at least as generous as the current plan; the selected catalogue package may exceed the requested number.
- A relative request such as “I need more data” means the next available tier above the current plan. “More minutes” first requires the service type—local or international—but should not require an exact number after that clarification.
- **I need 10 GB and 50 SMS.** produced **Data Plus 7 Days** at AED 239 with 25.0 GB, 250 local minutes, 80 international minutes, and 60 SMS. The short fallback response was **The package plan was updated for the requested service levels.**
- **I need 200 minutes.** produced **Do you mean local minutes or international minutes?** Answering **Local** retained Data Plus 7 Days because it already included 250 local minutes. The response was **I reviewed that request, but your current package is still the closest valid match, so I kept it unchanged.**
- Requests for the previous or original recommendation are handled locally. If there is no earlier plan, the response is **You are already viewing the earliest recommendation in this path.**
- Greetings are answered locally and do not change the recommendation.
- If Gemini is rate-limited, the implemented customer copy begins **The Gemini request limit was reached** and the app continues with the local catalogue. It either reports that it updated the plan locally, kept the closest valid match, or asks which of data, local minutes, international minutes, SMS, price, or validity should change.
- If a message cannot yet become requirements, the current implementation asks a clarification and preserves the plan. The former message “I could not safely interpret that request” is not present in the current code path.
- API/request errors are inserted as the assistant message and also shown as an error toast; entered conversation and the current plan remain available.

#### Observed three-day split request

The separate three-day request was:

> I need 10 GB on Day 1 and 2 GB combined across Days 2 and 3. Keep everything else the same.

The current fallback path did **not** render the requested split. It returned one **Data Plus 3 Days** package at AED 109 with 10.0 GB, 90 local minutes, 30 international minutes, and 25 SMS. There was no segment timeline, and the displayed total was 10 GB rather than the stated 12 GB. This must be documented as observed behavior, not rewritten as the expected split result.

### H. Final recommendation and activation

- Selecting **Continue with this plan** opens **Step 4 of 4 – Final recommendation**.
- The heading is **Your plan is ready**. The screen shows destination, dates, inclusive trip length, **Complete package sequence**, package order, coverage days, allowances, total price, combined validity, activation count, and partner status.
- The final card renders an activation code beside each package. Separately, the **ACTIVATION ORDER** sequence masks its code until acknowledgement. This distinction is important: in the current UI, the code is already visible in the package card before acknowledgement even though the activation sequence, Copy, dialer, and Done controls remain protected.
- **Confirm your preferred partner** instructs: **Before activation, make sure your phone is connected to a preferred partner network.**
- Before acknowledgement, the activation-sequence code is masked, **Copy activation codes**, the activation-aware dialer button, and **Done** are disabled, and the message is **Confirm the preferred partner connection above to reveal activation codes.**
- Checking **I confirm that I am connected to a preferred partner network.** reveals the activation-sequence code and enables the protected actions. The toast is **Preferred partner confirmed. Activation codes are now available.**
- **Copy activation codes** copies an ordered list. The button briefly becomes **Copied** and the toast is **Activation codes copied in order.**
- For one activation, the button reads **Open code in dialer** and the confirmation says **The activation code will be placed in the dialer. Nothing is activated automatically.** For multiple activations, it reads **Open first code in dialer** and says **The first activation code will be placed in the dialer. Nothing is activated automatically.** Both use the title **Open your dialer?** and the confirm action **Open dialer**.
- Guidance under the sequence reads **Activate each package in the displayed order and confirm the carrier response before continuing.** and **No package will activate automatically.**
- **Save Selection** is available independently of the acknowledgement. **Done** requires acknowledgement; otherwise the toast is **Acknowledge the network note before finishing.**
- The final-screen back arrow returns to Step 3 for the active journey. When viewing a saved plan, it returns to the landing page. **Exit** returns to the landing page.
- **Done** returns to the roaming landing page and leaves the completed plan available as Recent Recommendation. **Start New** clears the draft and opens Step 1. **Home** returns to the application home screen.

### I. Saved recommendations

- Select **Save Selection** on the final screen. Success changes the button to disabled **Saved** and shows **Recommendation saved.**
- Saving the same recommendation again does not duplicate it; the toast is **Recommendation already saved.**
- A maximum of four recommendations is kept. Saving a fifth drops the oldest session-saved item.
- **View Details** opens the saved final recommendation with partner acknowledgement reset, so protected actions must be acknowledged again.
- **Remove** opens **Remove saved recommendation?** with **This removes the saved plan from the current session.** Actions are **Remove** and **Cancel**. Successful removal shows **Saved recommendation removed.**
- Saves persist through navigation and refresh while the same signed-in Flask session remains active. They are session-scoped, not durable account records, and **do not survive logout** because logout clears the entire session.

### J. Navigation and visible state

- Forward steps use forward/rightward motion; workflow arrows, **Back**, and browser Back use reverse/leftward motion. Reduced-motion preferences minimize animation.
- **Exit** returns to the landing page without clearing the current draft. Re-entering the workflow in the same session restores the last saved step and inputs.
- **Start New** deletes the roaming workflow draft and clears destination, dates, recommendation, chat, saved selection state, completion state, and acknowledgement state. It does not delete separately saved recommendation cards.
- **Done** marks the current plan complete and returns to the landing page; it does not act as **Start New**.
- Partner acknowledgement is deliberately not restored from the workflow draft. Refreshing or opening a saved plan requires the acknowledgement again.
- Logout clears workflow drafts, current recommendation/conversation state, recent recommendation access for that session, and all session-saved recommendation cards. Database-backed seeded account data remains.

### K. Mobile/PWA behavior

- On mobile and in installed standalone mode, the customer UI fills the screen; the desktop Phone/Expanded preview controls and simulated device chrome are hidden.
- Safe-area insets protect the header, bottom navigation, sheets, and controls around an iPhone notch/home indicator.
- The bottom navigation remains fixed. When an editable field opens the mobile keyboard, the app hides the bottom navigation, keeps a stable application height, and scrolls the focused chat area toward the top so the keyboard occupies the lower visual viewport.
- The page viewport prevents user scaling/zooming in the installed/mobile experience.
- Safari may show **Add this app to your Home Screen**. The sheet instructs the customer to use Share, **Add to Home Screen**, optionally **Open as Web App**, then **Add**.
- When an update is waiting, the visible notice is **An update is available. Refresh when you are ready.** with **Refresh** and **Later**.
- The offline fallback says **We cannot reach e& Care right now** and **Your account information stays on the server and is not stored on this offline screen. Check your connection, then try again.** The status changes among **Server unavailable**, **Checking connection**, and **Connection restored**; the action is **Try again** or **Continue**. The recommender itself requires the server/tunnel to be reachable.

## Button and control inventory

| UI Label | Screen/Step | Enabled When | Action | Result |
|---|---|---|---|---|
| Roaming | Dashboard bottom navigation | Signed in | Opens roaming area | Shows landing or restored roaming draft |
| ← (Back to prior application area) | Roaming page header | Always | Leaves roaming screen | Returns to prior application area |
| Start planning | Landing | Always | Begins/re-enters planning | Opens Destination; resets first if the prior journey is completed |
| Recent recommendation chevron | Landing | A completed current recommendation exists | Opens recent plan | Shows Final recommendation |
| ← (Back to roaming landing) | Step 1 | Always | Leaves Step 1 | Shows landing without resetting draft |
| Continue | Step 1 | A destination is selected | Accepts destination | Opens Travel dates |
| Exit | Steps 1–4 | Always | Leaves workflow view | Shows landing without acting as Start New |
| Edit | Step 2 | Always | Edits selected destination | Returns to Step 1 |
| Back | Step 2 | Always | Returns one step | Opens Step 1 with selection retained |
| Continue | Step 2 | Both dates are valid | Requests recommendation | Shows loading, then Step 3 |
| More details / Hide details | Step 3 | A recommendation exists | Toggles detail panel | Shows/hides scaled usage and Why this fits |
| ↑ (Send adjustment) | Step 3 chat | Chat contains non-whitespace text | Sends refinement | Shows reviewing state, clarification, updated plan, or error |
| Continue with this plan | Step 3 | A recommendation exists | Accepts current plan | Opens Final recommendation |
| ← (Back to recommendation adjustment) | Step 4 | Always | Returns from final plan | Opens Step 3, or landing for a saved-plan view |
| Preferred-partner checkbox | Step 4 | Always | Records acknowledgement | Reveals sequence code; enables Copy, dialer, and Done |
| Copy activation codes | Step 4 | Partner acknowledged | Copies ordered codes | Brief **Copied** state and success toast |
| Open code in dialer / Open first code in dialer | Step 4 | Partner acknowledged; label depends on whether the plan has one or multiple activations | Opens confirmation | Confirming places the code, or the first code in a sequence, in the device dialer |
| Save Selection | Step 4 | Current recommendation is not already saved | Saves to session | Becomes disabled **Saved** and adds landing card |
| Done | Step 4 | Partner acknowledged | Completes current journey | Returns to roaming landing |
| Start New | Step 4 | Always | Clears active draft | Opens a fresh Destination step |
| Home | Step 4 | Always | Leaves roaming | Opens application home |
| View Details | Saved card | Saved card exists | Restores saved plan | Opens Final recommendation with acknowledgement reset |
| Remove | Saved card | Saved card exists | Opens confirmation | **Remove** deletes card; **Cancel** preserves it |
| Phone | Desktop preview | Desktop width | Chooses phone frame | Displays fixed phone-sized surface |
| Expanded | Desktop preview | Desktop width | Chooses wide layout | Expands app surface while keeping preview controls reachable |

## User input inventory

| Input | Screen | Required? | Format | Validation | Example |
|---|---|---:|---|---|---|
| Email or phone | Sign in | Yes | Email address or UAE phone number | Empty submission prompts for sign-in details; invalid credentials remain on sign-in | `aisha@example.test` |
| Password | Sign in | Yes | Masked password text | Required; never include it in manual imagery | Omitted intentionally |
| Destination search/selection | Step 1 | Yes | Prefix text plus one supported country selection | Search may be empty; Continue requires a selected country | Search `B`; select France |
| Departure | Step 2 | Yes | Browser date input, `YYYY-MM-DD` in captured browser | Next calendar day or later; must be on/before Return | `2026-08-29` |
| Return | Step 2 | Yes | Browser date input, `YYYY-MM-DD` in captured browser | Must be on/after Departure | `2026-09-04` |
| Chat message | Step 3 | No | Free text; Enter sends, Shift+Enter adds a line | Blank text cannot be sent; maximum accepted request text is bounded by the backend | `I need 10 GB and 50 SMS.` |
| Preferred-partner acknowledgement | Step 4 | Required for activation actions/Done | Checkbox | Copy, dialer, and Done remain disabled until checked | Confirm connection to a preferred partner network |

## User-facing message inventory

| Situation | Current customer-facing text / behavior |
|---|---|
| No recent plan | **No recent trip yet** / **Complete a recommendation to see it here.** |
| No country search matches | **No countries begin with that search. Try another name.** |
| Destination missing | **Continue** remains disabled; backend safeguard: **Choose a destination first.** |
| Dates incomplete | Trip duration is hidden and **Continue** remains disabled |
| Return before departure | **Return date must be on or after the departure date.** |
| Past date | **Choose travel dates in the future.** |
| Loading | **Finding your best fit** plus the four phases listed above |
| Catalogue unavailable | **The package catalogue is temporarily unavailable.** |
| No package | **No suitable package found** / **Try another adjustment. Your destination and dates remain saved.** / **Return to recommendation** |
| Blank chat | **Enter an adjustment first.** |
| Chat waiting | **Reviewing that adjustment…** |
| Ambiguous minutes | **Do you mean local minutes or international minutes?** |
| Unchanged closest plan | **I reviewed that request, but your current package is still the closest valid match, so I kept it unchanged.** |
| Updated service levels | **The package plan was updated for the requested service levels.** |
| Earliest history | **You are already viewing the earliest recommendation in this path.** |
| Gemini rate/frequency fallback | Begins **The Gemini request limit was reached**; continues locally with an adjustment, unchanged-plan explanation, or clarification |
| Recommendation changed/restored | **Recommendation reviewed.** / **Recommendation restored.** |
| Save | **Recommendation saved.** / **Recommendation already saved.** |
| Save failure | **The recommendation is incomplete and could not be saved.** |
| Remove | **Remove saved recommendation?** / **This removes the saved plan from the current session.** / **Saved recommendation removed.** |
| Before partner confirmation | **Confirm the preferred partner connection above to reveal activation codes.** |
| Partner confirmed | **Preferred partner confirmed. Activation codes are now available.** |
| Activation guidance | **Activate each package in the displayed order and confirm the carrier response before continuing.** / **No package will activate automatically.** |
| Copy success | **Activation codes copied in order.** and temporary **Copied** button text |
| Dialer confirmation | **Open your dialer?** / **The activation code will be placed in the dialer. Nothing is activated automatically.** for one activation; the sentence adds **first** for multiple activations |
| Done without acknowledgement | **Acknowledge the network note before finishing.** |
| Offline | **We cannot reach e& Care right now** and the server-status/retry messages listed in the PWA section |

## Minimum User Manual safety / POC notes

The formal User Manual should state these points once, clearly and without repeating them on every instruction:

- This internship application is a proof of concept and is not production approved.
- Customer profiles, usage, prices, roaming packages, partner status, and activation codes shown are simulated/seeded data, not live account information or current commercial offers.
- **Save Selection** stores only in the current application session; it does not add or purchase a package on a live account.
- Copying or opening an activation code does not activate a package automatically. Do not present the captured codes as live e& activation instructions.
- The preferred-partner acknowledgement is a user confirmation, not a live carrier-network verification.

## Desktop versus mobile

| Behavior | Mobile/PWA | Desktop |
|---|---|---|
| App surface | Full-screen responsive UI | Simulated Phone frame by default |
| Preview controls | Hidden | **Phone** and **Expanded** controls appear outside/above the app surface |
| Expanded layout | Not applicable; already full width | App widens to a maximum 1040 px surface; content remains centered and the bottom navigation becomes a centered floating bar |
| Device chrome | Browser/standalone safe areas; no simulated notch in captured mobile UI | Phone mode shows notch, status bar, device border, and home indicator; Expanded hides simulated notch/status/home indicator |
| Bottom navigation | Fixed to safe-area bottom; hidden while keyboard is open | Fixed within Phone frame; centered floating bar in Expanded mode |
| Keyboard | Focused chat is aligned near the top and navigation hides while the software keyboard occupies the lower viewport | Standard desktop text entry; no software-keyboard adaptation |
| Display preference | Standalone/mobile presentation | Phone/Expanded choice is remembered in that browser’s local storage |

## Screenshot manifest

All authenticated screenshots below contain seeded POC customer/package data. No password, API key, session identifier, Gemini interaction identifier, terminal, developer tools, or debugging overlay is visible.

| Priority | Screenshot | Workflow Step | What It Shows | User Action Before Screenshot | Important UI Elements | Suggested Manual Caption | Data Note |
|---|---|---|---|---|---|---|---|
| ESSENTIAL | [01_login.png](screenshots/mobile/01_login.png) | Access | Empty sign-in validation state | Open the application and submit with both fields blank | Email/phone, Password, Show, Remember me, Sign in, Fill sign-in details | Figure 1. Enter the required sign-in details to access e& Care. | No entered credentials |
| ESSENTIAL | [02_app_home.png](screenshots/mobile/02_app_home.png) | Access | Authenticated dashboard and roaming navigation | Sign in as seeded Aisha | Account status, service cards, Roaming bottom tab | Figure 2. Open Roaming from the application navigation. | Seeded POC account/bill data |
| ESSENTIAL | [03_roaming_landing.png](screenshots/mobile/03_roaming_landing.png) | Landing | Clean roaming entry with no recent trip | Select Roaming | Full title, travel image, Start planning, empty recent card | Figure 3. Start a new roaming plan. | Seeded account shell; no plan yet |
| ESSENTIAL | [04_destination_empty.png](screenshots/mobile/04_destination_empty.png) | Step 1 – Destination | Destination step before selection | Select Start planning | Progress, search, country list, disabled Continue, Back/Exit | Figure 4. Search for the destination country. | Seeded supported-country catalogue |
| SUPPORTING | [05_destination_search.png](screenshots/mobile/05_destination_search.png) | Step 1 – Destination | Prefix search using `B` | Enter `B` in Search countries | 3 countries; Bahrain, Belgium, Brazil | Figure 5. Country search matches the beginning of a country name. | Seeded country catalogue |
| ESSENTIAL | [06_destination_selected.png](screenshots/mobile/06_destination_selected.png) | Step 1 – Destination | France selected | Select France | Selected check mark and enabled Continue | Figure 6. Select a country, then tap Continue. | Seeded country catalogue |
| ESSENTIAL | [07_dates_empty.png](screenshots/mobile/07_dates_empty.png) | Step 2 – Travel dates | Dates before entry | Select Continue from Destination | France, Edit, Departure, Return, disabled Continue | Figure 7. Enter departure and return dates. | Seeded destination |
| ESSENTIAL | [08_dates_selected.png](screenshots/mobile/08_dates_selected.png) | Step 2 – Travel dates | Valid seven-day range | Enter 29 Aug–4 Sep 2026 | Both dates, 7-day duration, enabled Continue | Figure 8. Check the inclusive trip duration, then continue. | Seeded destination and test dates |
| SUPPORTING | [09_analysis_loading.png](screenshots/mobile/09_analysis_loading.png) | Analysis | Live recommendation loading state | Select Continue on valid dates | Finding your best fit; coverage phase | Figure 9. Wait while the app analyses the trip and recent usage. | No private identifiers |
| ESSENTIAL | [10_initial_recommendation.png](screenshots/mobile/10_initial_recommendation.png) | Step 3 – Recommendation | Initial Roam Essentials result | Wait for analysis | Package, AED 69, 7 days, totals, activation count | Figure 10. Review the usage-based recommendation. | Seeded usage/package data |
| SUPPORTING | [11_initial_recommendation_full.png](screenshots/mobile/11_initial_recommendation_full.png) | Step 3 – Recommendation | Lower recommendation card and actions | Scroll within Step 3 | Allowance totals, More details, chat, Continue with this plan | Figure 11. Review totals and available recommendation actions. | Seeded usage/package data |
| SUPPORTING | [13_more_details_open.png](screenshots/mobile/13_more_details_open.png) | Step 3 – Details | Expanded usage explanation | Select More details | Scaled usage, Why this fits, Hide details | Figure 12. Expand More details to compare the plan with recent usage. | Seeded usage/package data |
| ESSENTIAL | [14_chat_ready.png](screenshots/mobile/14_chat_ready.png) | Step 3 – Chat | Empty adjustment composer | Scroll to Adjust recommendation | Placeholder, send arrow, Continue with this plan | Figure 13. Enter a change in Adjust recommendation. | Seeded current plan |
| ESSENTIAL | [15_chat_exact_request.png](screenshots/mobile/15_chat_exact_request.png) | Step 3 – Chat | Exact request sent | Send “I need 10 GB and 50 SMS.” | User bubble and reviewing state | Figure 14. Submit exact minimum service requirements. | Seeded current plan; test chat text |
| ESSENTIAL | [16_chat_updated_recommendation.png](screenshots/mobile/16_chat_updated_recommendation.png) | Step 3 – Updated plan | Data Plus 7 Days result | Wait for exact-request response | AED 239; 25 GB; 250/80 minutes; 60 SMS | Figure 15. Review the updated plan returned for the request. | Seeded fallback package result |
| ESSENTIAL | [17_chat_ambiguous_request.png](screenshots/mobile/17_chat_ambiguous_request.png) | Step 3 – Clarification | Minutes ambiguity prompt | Send “I need 200 minutes.” | User request; local/international question | Figure 16. Clarify which type of minutes should change. | Seeded plan; test chat text |
| ESSENTIAL | [18_chat_clarification_answer.png](screenshots/mobile/18_chat_clarification_answer.png) | Step 3 – Clarification | Answer and unchanged-plan response | Answer “Local” | Full clarification exchange and assistant result | Figure 17. The app applies the clarification to the current plan. | Seeded plan; test chat text |
| OPTIONAL | [20_split_request.png](screenshots/mobile/20_split_request.png) | Step 3 – Split request | Three-day day-specific request sent | Send the documented Day 1/Days 2–3 request | Request bubble and reviewing state | Figure 18. Submit a time-specific data requirement. | Seeded three-day plan; test chat text |
| OPTIONAL | [21_split_result.png](screenshots/mobile/21_split_result.png) | Step 3 – Split result | Actual unsplit Data Plus 3 Days result | Wait for split-request response | AED 109; 10 GB; 90/30 minutes; 25 SMS | Figure 19. Current fallback result for the time-specific request. | Seeded fallback result; does not match requested 12 GB split |
| ESSENTIAL | [23_save_selection.png](screenshots/mobile/23_save_selection.png) | Step 4 – Save | Final page immediately before save | Scroll to Save Selection | Masked sequence, disabled activation actions, Save Selection | Figure 20. Save the selected plan for the current session. | Seeded package/code data; sequence code masked |
| ESSENTIAL | [24_saved_recommendations.png](screenshots/mobile/24_saved_recommendations.png) | Landing – Saved | Saved recommendation card | Select Save Selection, then Exit | Saved card, View Details, Remove, recent card | Figure 21. Open or remove a session-saved recommendation. | Seeded saved plan |
| SUPPORTING | [26_remove_saved.png](screenshots/mobile/26_remove_saved.png) | Landing – Saved | Removal confirmation sheet | Select Remove on a saved card | Remove saved recommendation?, Remove, Cancel | Figure 22. Confirm before removing a saved recommendation. | Blurred background contains seeded plan data |
| ESSENTIAL | [27_continue_with_plan.png](screenshots/mobile/27_continue_with_plan.png) | Step 3 – Accept | Updated plan with primary acceptance action | Complete split test and scroll to chat/actions | Assistant message and Continue with this plan | Figure 23. Continue when the displayed plan is acceptable. | Seeded fallback result |
| ESSENTIAL | [28_final_recommendation.png](screenshots/mobile/28_final_recommendation.png) | Step 4 – Final | Top of final plan | Select Continue with this plan | Trip dates, package sequence, code, price, allowances | Figure 24. Review the complete final package sequence. | Seeded package and activation code |
| ESSENTIAL | [29_activation_before_acknowledgement.png](screenshots/mobile/29_activation_before_acknowledgement.png) | Step 4 – Activation | Protected one-package state before acknowledgement | Scroll to partner note without checking it | Unchecked box, masked sequence, disabled Copy/**Open code in dialer**/Done | Figure 25. Confirm the preferred partner before using activation actions. | Seeded one-package plan; activation sequence code masked |
| ESSENTIAL | [30_partner_acknowledged.png](screenshots/mobile/30_partner_acknowledged.png) | Step 4 – Activation | Enabled one-package state after acknowledgement | Check preferred-partner box | Checked state, visible code, enabled **Open code in dialer** and Done | Figure 26. Acknowledgement reveals and enables the single activation code. | Seeded activation code |
| ESSENTIAL | [31_activation_codes.png](screenshots/mobile/31_activation_codes.png) | Step 4 – Activation | Single activation order and revealed code | Acknowledge preferred partner | Ordered package, code, Copy, **Open code in dialer** | Figure 27. Use the revealed activation code after confirming the preferred partner. | Seeded activation code; not live |
| ESSENTIAL | [32_final_actions.png](screenshots/mobile/32_final_actions.png) | Step 4 – Actions | Complete one-package action area without clipping | Acknowledge and scroll through final actions | Copy, **Open code in dialer**, Save Selection, Done, Start New, Home | Figure 28. Choose the final action after reviewing the one-package plan. | Seeded activation code; not live |
| SUPPORTING | [33_done_landing.png](screenshots/mobile/33_done_landing.png) | Landing – Complete | Landing after Done | Select Done | Saved card and recent recommendation | Figure 29. Done returns to the roaming landing page. | Seeded completed/saved plan |
| SUPPORTING | [34_start_new.png](screenshots/mobile/34_start_new.png) | Step 4 – Navigation | Start New action on completed plan | Open completed/saved plan and acknowledge | Done, Start New, Home | Figure 30. Select Start New to clear the active trip draft. | Seeded completed plan/code |
| SUPPORTING | [35_new_trip_reset.png](screenshots/mobile/35_new_trip_reset.png) | Step 1 – Reset | Fresh destination step after reset | Select Start New | No selected country; disabled Continue | Figure 31. A new trip starts with the previous draft cleared. | Seeded country catalogue |
| OPTIONAL | [36_back_navigation.png](screenshots/mobile/36_back_navigation.png) | Step 1 – Back | Destination retained after returning from dates | Select Back from Travel dates; search France | Step 1 context, France selected, enabled Continue | Figure 32. Back returns to the prior step without losing the selection. | Seeded country catalogue; single-result card expands vertically |
| ESSENTIAL | [37_invalid_date.png](screenshots/mobile/37_invalid_date.png) | Step 2 – Validation | Return before departure | Enter an earlier Return date | Exact validation message and disabled Continue | Figure 33. Correct the return date before continuing. | Test dates only |
| SUPPORTING | [38_empty_required_fields.png](screenshots/mobile/38_empty_required_fields.png) | Step 1 – Empty search | No destination matches | Search `Zzz` | 0 countries, empty message, disabled Continue | Figure 34. Continue remains unavailable until a supported country is selected. | Seeded country catalogue; test search text |
| SUPPORTING | [desktop/01_home_phone_frame.png](screenshots/desktop/01_home_phone_frame.png) | Desktop – Home | Home inside Phone mode | Sign in on desktop | Simulated device frame and dashboard | Desktop Figure 1. Phone mode presents the app in a virtual device. | Seeded POC account/bill data |
| SUPPORTING | [desktop/02_roaming_landing.png](screenshots/desktop/02_roaming_landing.png) | Desktop – Landing | Roaming landing in Phone mode | Open Roaming | Travel visual, Start planning, saved card | Desktop Figure 2. Roaming landing page in Phone mode. | Seeded saved plan from capture session |
| SUPPORTING | [desktop/03_destination.png](screenshots/desktop/03_destination.png) | Desktop – Destination | France selected in Phone mode | Start planning and select France | Device chrome, stepper, selected row, Continue | Desktop Figure 3. Destination selection uses the same phone workflow. | Seeded country catalogue |
| SUPPORTING | [desktop/04_recommendation.png](screenshots/desktop/04_recommendation.png) | Desktop – Recommendation | Initial seven-day recommendation | Enter valid dates and wait | Plan, totals, More details | Desktop Figure 4. Review the recommendation in the virtual phone. | Seeded fallback package result |
| SUPPORTING | [desktop/05_chat.png](screenshots/desktop/05_chat.png) | Desktop – Chat | Chat composer in Phone mode | Scroll to Adjust recommendation | Placeholder, send arrow, Continue with this plan | Desktop Figure 5. The adjustment chat remains available in Phone mode. | Seeded current plan |
| SUPPORTING | [desktop/06_final_plan.png](screenshots/desktop/06_final_plan.png) | Desktop – Final | Final seven-day package in Phone mode | Continue with initial plan | Trip, sequence, code, price, allowances | Desktop Figure 6. Final plan in the virtual phone frame. | Seeded package and activation code |
| OPTIONAL | [desktop/07_expanded_mode.png](screenshots/desktop/07_expanded_mode.png) | Desktop – Expanded | Same final plan in wide layout | Select Expanded | Wide plan card and centered bottom navigation | Desktop Figure 7. Expanded mode uses a wider customer surface. | Seeded package and activation code |

## Screenshot quality review

- Reviewed all 41 retained images individually at original resolution.
- Mobile images are consistently `430 × 900`. Six desktop Phone-mode images are `432 × 886`; Expanded is `1040 × 920`.
- Exact hash comparison found no remaining duplicate images.
- Login contains no entered credential. No screenshot contains a password, API key, cookie/session value, interaction ID, terminal, developer tools, or debug overlay.
- The only person/account information shown is the intentionally seeded POC first name/avatar. All prices, usage, package details, saved plans, dates, and activation codes are simulated.
- Important controls are readable. Half-scrolled captures are retained only where scrolling is the subject or is needed to show the relevant card/action; the final-actions frame was recaptured so every documented action is fully visible.
- No destructive action was confirmed during the screenshot pass. The Remove image shows the confirmation before deletion.

## Final capture report

| Item | Result |
|---|---|
| Total screenshots | 41 |
| Mobile screenshots | 34 |
| Desktop screenshots | 7 |
| Seeded user | Aisha (`aisha@example.test`); password omitted |
| Destination | France |
| Main mobile dates | 29 Aug–4 Sep 2026 (7 days inclusive) |
| Split-test dates | 12–14 Sep 2026 (3 days inclusive) |
| Desktop dates | 4–10 Aug 2026 (7 days inclusive) |
| Initial result | Roam Essentials 7 Days; AED 69; 3 GB; 100 local; 35 international; 30 SMS; one activation |
| Exact refinement | “I need 10 GB and 50 SMS.” → Data Plus 7 Days; AED 239; 25 GB; 250 local; 80 international; 60 SMS |
| Clarification | “I need 200 minutes.” → local/international question; “Local” retained the 250-local-minute current plan |
| Split test | Tested; actual fallback returned one Data Plus 3 Days plan with 10 GB and no segment timeline |
| Save/restore | Save, duplicate-safe state, landing card, View Details behavior, and Remove confirmation tested |
| Final activation flow | Pre-ack lock, acknowledgement, sequence code, Copy/dialer enabled state, Done, Start New, and Home captured |
| Physical/PWA differences | Full-screen mobile with safe areas and keyboard adaptation; desktop Phone frame plus Expanded mode |

### Requested images intentionally not retained

- `12_more_details_closed.png`: visually identical to `11_initial_recommendation_full.png`; removed to avoid redundancy.
- `19_chat_clarified_result.png`: the plan was unchanged and its recommendation view was identical to `16_chat_updated_recommendation.png`; the actual clarification/result remains visible in `18_chat_clarification_answer.png`.
- `22_split_timeline.png`: the current fallback result returned no segments, so the timeline was not rendered.
- `25_saved_view_details.png`: the restored final view was identical to `28_final_recommendation.png`; removed to avoid redundancy.
- `39_chat_error_or_clarification.png`: no additional useful, non-destructive chat error existed beyond the clarification and current validation/fallback captures.

### Observed inconsistencies or potentially confusing behavior

1. The split request stated 10 GB on Day 1 plus 2 GB across Days 2–3, but the fallback result displayed 10 GB total, a single unsplit package, and no segment timeline. This differs from the split/segment behavior described in the README and from the expected 12 GB meaning in the capture brief.
2. The final package card displays its activation code before preferred-partner acknowledgement, while the activation-sequence row masks the same code and disables Copy/dialer/Done. The acknowledgement therefore protects actions and one code rendering, but does not fully conceal the code on the page.
3. The final details label **Partner status** as **Connected to preferred partner** before the customer checks the confirmation box. The box remains the actual gate for protected controls, but the status wording may imply verification too early.
4. The README refers to an explicit **Gemini limit** chat label; current UI copy uses the sentence **The Gemini request limit was reached…** rather than a standalone label.
5. Filtering to one destination makes the single country group/card unusually tall on mobile. It remains usable, but the presentation is visually disproportionate.
6. The compact app-header title is ellipsized as **Roaming Reco…** on Phone/mobile layouts, although the full **Roaming Recommender** heading appears immediately below it.
7. No separate SDD file was present in the repository, so only current UI/source behavior and README statements could be compared.

These are documentation findings only. No application, test, configuration, or existing documentation file was changed to alter the observed behavior.
