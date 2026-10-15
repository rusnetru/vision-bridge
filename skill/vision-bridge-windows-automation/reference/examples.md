# Worked flows

## Write and verify text in Notepad
```
capture("Notepad")                       -> find the document element, e.g. u0 (role textbox)
act("u0", "set_value", value="Report draft")
act("u0", "read")                        -> content == "Report draft"? continue : retry
```

## Fill a desktop form
```
capture("Customer card")                 -> read `text`, map labels to textbox ids
act("u4", "set_value", value="ACME LLC")
act("u7", "set_value", value="7701234567")
act("u4", "read"); act("u7", "read")     -> verify both
find("Save", target="Customer card")     -> u12
act("u12", "click")
wait_for("Saved", target="Customer card", timeout_s=15)
```

## Click through an installer
```
wait_for("Next", target="Setup", timeout_s=60)  -> u3
act("u3", "click")
capture("Setup")                         -> read license text, find the accept checkbox
act("u5", "click")                       -> re-capture, confirm state.checked == true
wait_for("Install", target="Setup")      -> confirm with the user, then click
wait_for("Finish", target="Setup", timeout_s=300)
```

## Electron app with a blind accessibility tree
```
capture("Slack")                         -> method_used == "ocr", ids start with "o"
find("General", target="Slack")          -> o14
act("o14", "click")
capture("Slack")                         -> confirm the channel opened
```

## Logged-in web page via the user's Chrome
```
browser_open(mode="cdp", cdp_url="http://localhost:9222")
browser_goto("https://example.com/dashboard")
capture("browser")                       -> b-ids
act("b9", "click")
browser_close()
```
