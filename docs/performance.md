# Bounded performance verification

The planner retains two-stage road routing and independent fuel validation.
Station selection skips stations with no possible route-segment hits before
creating a local coordinate transformer. A routing budget owns one lazily created
HTTPX client for the plan's actual attempts and closes it after routing, including
on failure. Each stream still receives a timeout derived from remaining time;
the three-attempt limit, deadline, response-size guard and routing policy remain.
Saved-plan hits and zero-distance requests do not create a provider client.

A local alternating replay compared the pre-change revision `7a89557` with both
improvements against identical historical normalized road responses. The ten
frozen benchmark journeys and Minneapolis–Charleston preserved complete ordered
candidate records, final route content, purchase quantities and tank balances.
Synthetic forward/reverse loops preserved distinct occurrences and unrounded
purchases. Seattle–Denver retained its coverage failure. No shared cache was
cleared or dataset activated.

On Minneapolis–Charleston, three warm samples per revision measured mean station
selection of 422 ms before and 180 ms after; transformer construction fell from
651 to 53. These are local-work measurements; timings varied on other routes.

A separate IPv4 experiment used the Django view and renderer on a temporary
single-threaded WSGI server inside Docker, with fresh per-revision database-cache
prefixes. Revision order was reversed for the second journey. Working-app caches
were retained; upstream provider cache state was unknown.

| Fresh purchase journey | Baseline HTTP | Changed HTTP | Provider attempts each |
| --- | ---: | ---: | ---: |
| Minneapolis → Charleston | 3.37 s | 2.21 s | 2 |
| Charleston → Minneapolis | 3.23 s | 2.11 s | 2 |

There was one fresh sample per journey/revision, followed by two cached repeats.
All twelve responses succeeded; eight actual provider attempts were made in
total. Changed cached repeats took 28–33 ms and made zero provider calls.
Transport traces showed two TCP/TLS setups for each baseline fresh plan and one
for each changed plan. The total timing difference also includes network/provider
variability and local-work changes; it is not an isolated client-reuse effect.

These samples establish neither a production percentile nor a nationwide SLA.
The earlier connection probe's 927 ms difference is not an application-speedup
claim. Provider waiting/downloads remain the main source of fresh-route latency.
