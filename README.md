# LearningX Alert Web

The project is currently at the read-only two-account feasibility gate. It does not send notifications or store Canvas tokens.

## Run the probe

Set the operator-owned Canvas origin and, for LearningX inspection, the approved LearningX hostnames:

```bash
read -r -p 'Canvas base URL: ' CANVAS_BASE_URL
export CANVAS_BASE_URL
read -r -p 'Allowed LearningX hosts, comma-separated: ' LEARNINGX_ALLOWED_HOSTS
export LEARNINGX_ALLOWED_HOSTS
python3 -m learningx_alert.feasibility courses
read -r -p 'Course IDs to inspect, space-separated: ' LEARNINGX_COURSE_IDS
python3 -m learningx_alert.feasibility inspect $LEARNINGX_COURSE_IDS
```

The program prompts for the Canvas token without echoing it. Do not place the token in a command, `.env` file, screenshot, issue, or Git commit.

Run automated checks with:

```bash
python3 -m unittest discover -v
```
