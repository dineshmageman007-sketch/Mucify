// Simulates the browser page the Qobuz probe runs in (fake fetch / XHR / localStorage / location)
// and checks that PROBE_JS captures the auth header and finds token-looking storage values.
const fs = require("fs");
const src = fs.readFileSync(process.argv[2], "utf8");
const probe = src.match(/PROBE_JS = r"""([\s\S]*?)"""/)[1];

const store = {
  "unrelated": "hello",
  "qobuz_user": JSON.stringify({ id: 1234567, user_auth_token: "AbCdEf0123456789_-AbCdEf0123456789" }),
};
global.localStorage = { get length() { return Object.keys(store).length; }, key: i => Object.keys(store)[i], getItem: k => store[k] };
global.location = { hostname: "play.qobuz.com" };
let sentHeaders = null;
global.window = global;
window.fetch = function (input, init) { sentHeaders = init && init.headers; return Promise.resolve({}); };
global.XMLHttpRequest = function () {}; XMLHttpRequest.prototype.setRequestHeader = function () {};

const run = () => JSON.parse(eval(probe));
let out = run();
console.assert(out.hook === null, "no header seen yet");
console.assert(out.ls.includes("AbCdEf0123456789_-AbCdEf0123456789"), "localStorage token found: " + JSON.stringify(out));
console.assert(out.uid === "1234567", "user id found");
// the player now makes an API call with the header
window.fetch("https://www.qobuz.com/api.json/0.2/x", { headers: { "X-User-Auth-Token": "HEADERTOKEN1234567890abcdef" } });
out = run();
console.assert(out.hook === "HEADERTOKEN1234567890abcdef", "fetch header captured: " + JSON.stringify(out));
// XHR path
const xo = XMLHttpRequest.prototype.setRequestHeader;
const x = new XMLHttpRequest(); x.setRequestHeader("x-user-auth-token", "XHRTOKEN1234567890abcdefgh");
out = run();
console.assert(out.hook === "XHRTOKEN1234567890abcdefgh", "xhr header captured: " + JSON.stringify(out));
console.log("PROBE SIM OK", JSON.stringify(out));
