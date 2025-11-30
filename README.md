# myStop

## Description

Integration with Avail Technologies myStop system so that you can track your bus!

## Component Creation:

- Systemwide Alerts - For Alerts that are not specific to the routes selected.
- Per Route Alerts - For Alerts that are specific to the routes selected.
- Stop Departure Time
- Support for various routes and stops.
- Support for multiple transit agencies at the same time.

## Configuration

1. Go to **Settings** → **Devices & Services**
2. Click **+ Add Integration**
3. Search for "myStop"
4. Select your Transit System or Manual Entry
5. Select your Bus Route
6. Select your Bus Stop

## Manual Configuration
1. Select **Manual Entry** on Agency Name Dropdown
2. See Chart Below for Options

| Field name                           | Type      | Required | Example               | Description                                                                       |
| ------------------------------------ | --------- | -------- | --------------------------------------  | --------------------------------------------------------------- |
| agency_name                          | Textbox   | Yes      | River Valley Transit                    | Specify the name of the transit agency                          |
| base_url                             | Textbox   | Yes      | https://my.ridervt.com/infopoint        | Specify the transit systems url in the myStop System            |
| stop_id                              | Textbox   | Yes      | 62                    | Specify the specific stop ID number in the myStop System                          |
