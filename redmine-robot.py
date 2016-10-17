#!/usr/bin/python
import time
import logging, logging.handlers
from daemon import runner
import json
import requests
import subprocess
import sys
from datetime import datetime

log_file = "/var/log/redmine-robot.log"

#Load configuration
fconf = open("config.json").read()
conf = json.loads(fconf)

#Loggin
logger = logging.getLogger("RedmineRobot")
if "loglevel" in conf:
  if str(conf["loglevel"]) == "DEBUG":
    logger.setLevel(logging.DEBUG)
  if str(conf["loglevel"]) == "ERROR":
    logger.setLevel(logging.ERROR)
  if str(conf["loglevel"]) == "INFO":
    logger.setLevel(logging.INFO)
else:
  logger.setLevel(logging.DEBUG)
formatter = logging.Formatter("%(asctime)s;%(levelname)s;%(message)s")
handler = logging.handlers.RotatingFileHandler(log_file, 'a', 100000, 10)
handler.setFormatter(formatter)
logger.addHandler(handler)

def debug(msg):
  if msg: 
    logger.debug(msg)
def info(msg):
  if msg: 
    logger.info(msg)
def error(msg):
  if msg: 
    logger.error(msg)
def list(l):
  logger.debug("Scheduled Issues")
  for i in l:
    logger.debug(i)

class Issue(object):
  def __init__(self, redmine, issue_json, tracker_json):
    debug("Creating Issue %s" % json.dumps(issue_json))
    self.redmine = redmine
    self.id = issue_json["id"]
    self.tracker_id = issue_json["tracker"]["id"]
    self.status_id = issue_json["status"]["id"]
    if "command" in tracker_json:
      self.command = tracker_json["command"]
      debug("Tracker command %s" % self.command)
    else:
      self.command = "echo 'Nothing to do!!!'"
      if ("cf_cmd_id" in tracker_json) and ("custom_fields" in issue_json):
        for cf in issue_json["custom_fields"]:
          debug("CF %s" % json.dumps(cf))
          if cf["id"] == tracker_json["cf_cmd_id"]:
            debug("CF value found %s" % cf["value"])
            self.command = cf["value"]
            break
        debug("CF command %s" % self.command)
      else:
        error("Command not found")
    inDate = issue_json["start_date"]
    inTime = ""         
    if ("cf_exec_time_id" in tracker_json) and ("custom_fields" in issue_json): 
      for cf in issue_json["custom_fields"]:
        debug("CF %s" % json.dumps(cf))
        if cf["id"] == tracker_json["cf_exec_time_id"]:
          debug("CF value found %s" % cf["value"])
          inTime = cf["value"]
          break
    if inTime == "":
      inDatetime = "%s 00:00" % (inDate)
    else:
      inDatetime = "%s %s" % (inDate, inTime)
    try:
      self.dt_exec = datetime.strptime(inDatetime, "%Y-%m-%d %H:%M")
      debug("Execute datetime %s" % inDatetime)
    except:
      self.dt_exec = datetime.now()
      error("Datetime not valid")
  @staticmethod
  def CreateIssuesList(redmine, issues_json, tracker_json):
    issues = []
    for issue_json in issues_json:
      issueOk = True
      if "filters" in tracker_json:
        debug("Checking filters")
        for f in tracker_json["filters"]:
          key = str(f)
          value = str(tracker_json["filters"][f])
          value = value.lower()
          debug("Filter %s = %s" % (key, value))
          if key.startswith("cf_"):
            debug("Filter %s is a custom field" % key)
            if "custom_fields" in issue_json:
              key = key.replace("cf_", "")
              debug("Custom field id is %s" % key)
              try:
                cfId = int(key)
                cfOk = False
                for cf in issue_json["custom_fields"]:
                  if cf["id"] == cfId:
                    cfValue = str(cf["value"])
                    cfValue = cfValue.lower()
                    debug("Custom fields founded %d = %s" % (cfId, cfValue))
                    cfOk = value == cfValue
                issueOk = issueOk and cfOk              
              except ValueError:
                issueOk = False
                error("Error trying to find custom field %s" % key)
            else:
              issueOk = False
          else:
            debug("Filter %s is not a custom field" % key)
      if issueOk: 
        debug("Issue #%d is ok" % issue_json["id"])
        issues.append(Issue(redmine, issue_json, tracker_json))
    return issues
  def getUrl(self):
    return "%s/issues/%d.json" % (self.redmine.getUrl(), self.id)
  def schedule(self):
    try:
      if self.status_id != conf["statuses"]["scheduled"]:
        r = requests.put(self.getUrl(), \
              headers={"Authorization": "Basic %s" % conf["user"]["auth"]}, \
              json={ \
                "issue": { \
                  "status_id": conf["statuses"]["scheduled"], \
                  "assigned_to_id": conf["user"]["id"] \
                  } \
                })
        result = r.status_code == 200
        if result:
          debug("Issue #%d scheduled" % self.id)
        else:
          error("Failed to schedule issue #%d" % self.id)
      else:
        result = False
        error("Failed to schedule issue #%d. Issue already scheduled." % self.id)
      return result
    except:
      e = sys.exc_info()[0]
      error(e)
      return False
  def executeCmd(self):
    try:
      debug("Executing command '%s'" % self.command)
      p = subprocess.Popen([self.command], stdout=subprocess.PIPE, stderr=subprocess.PIPE, shell=True)
      out, err = p.communicate()
      debug(out)
      error(err)
      if p.returncode == 0:
        result = [True, out + err]
      else:
        result = [False, out + err]
    except:
      e = sys.exc_info()[0]
      result = [False, e]
      error(e)
    return result
  def execute(self):  
    try:
      debug("Executing issue #%d" % self.id)  
      r = requests.get(self.getUrl(), \
            headers={"Authorization": "Basic %s" % conf["user"]["auth"]})
      result = r.status_code == 200
      if result and (r.json()["issue"]["status"]["id"] == conf["statuses"]["scheduled"]):
        debug("Issue #%d schedule is ok" % self.id)
        r = requests.put(self.getUrl(), \
              headers={"Authorization": "Basic %s" % conf["user"]["auth"]}, \
              json={ \
                "issue": { \
                  "status_id": conf["statuses"]["execution"] 
                  } \
                })
        result = r.status_code == 200
        if result:
          # Execute action
          e = self.executeCmd();      
          # Finalize issue
          if e[0]:
            r = requests.put(self.getUrl(), \
                  headers={"Authorization": "Basic %s" % conf["user"]["auth"]}, \
                  json={ \
                    "issue": { \
                      "status_id": conf["statuses"]["completed"],
                       "notes": e[1]
                      } \
                    })
            result = r.status_code == 200
            if result:
              debug("Issue #%d completed" % self.id)
          else:
            r = requests.put(self.getUrl(), \
                  headers={"Authorization": "Basic %s" % conf["user"]["auth"]}, \
                  json={ \
                    "issue": { \
                      "status_id": conf["statuses"]["canceled"],
                      "notes": e[1]
                      } \
                    })
            result = r.status_code == 200        
            if result:
              debug("Issue #%d completed" % self.id)
      return result
    except:
      e = sys.exc_info()[0]
      error(e)
      return False
  def __str__(self):
    return "Issue #%d scheduled to %s" % (self.id, self.dt_exec.strftime("%Y-%m-%d %H:%M:%S") )
    
class Redmine(object):
  def __init__(self):
    self.scheduled_issues = self.getIssues(conf["statuses"]["execution"])
    self.scheduled_issues.extend(self.getIssues(conf["statuses"]["scheduled"]))
  def getUrl(self):
    return "%s://%s" % (conf["redmine"]["protocol"], conf["redmine"]["address"])
  def getIssues(self, status):
    issues = []
    try:
      for user_id in ["!*", conf["user"]["id"]]:
        for project in conf["projects"]:
          for tracker in conf["trackers"]:
            filters = {}
            filters["tracker_id"] = tracker["id"]
            filters["status_id"] = status
            filters["assigned_to_id"] = user_id
            if "filters" in tracker:
              for e in tracker["filters"]:
                key = str(e)
                value = str(tracker["filters"][e])
                debug("%s %s" %(key, value))
                filters[key] = value
            debug(filters)
            r = requests.get("%s/projects/%s/issues.json" % (self.getUrl(), project["identifier"]), \
                  headers={"Authorization": "Basic %s" % conf["user"]["auth"]}, \
                  params=filters)
            if r.status_code == 200:
              issues.extend(Issue.CreateIssuesList(self, r.json()["issues"], tracker))
    except:
      exc_type, exc_value, exc_traceback = sys.exc_info()
      error(exc_type)
      error(exc_value)
      error(exc_traceback)
    return issues
  def scheduler(self):
    issues = self.getIssues(conf["statuses"]["ready"])
    for issue in issues:
      if issue.schedule():
        self.scheduled_issues.append(issue)
  def execute(self):
    self.scheduled_issues.sort(key=lambda issue: issue.dt_exec)
    list(self.scheduled_issues)
    now = datetime.now()
    continue_exec = True
    while self.scheduled_issues and continue_exec:
      issue = self.scheduled_issues[0]
      continue_exec = issue.dt_exec <= now
      if continue_exec:
        debug("Execute issue #%d" % issue.id)
        if issue.execute():
          self.scheduled_issues.pop(0)
  def getReadyIssues(self):
    issues = self.getIssues(conf["statuses"]["ready"])
    for issue in issues:
      issue.printIssue()
      issue.schedule()
      issue.execute()
  def getCompletedIssues(self):
    issues = self.getIssues(conf["statuses"]["completed"])
    for issue in issues:
      issue.printIssue()

class App():
  def __init__(self):
    self.stdin_path = '/dev/null'
    self.stdout_path = '/dev/tty'
    self.stderr_path = '/dev/tty'
    self.pidfile_path =  '/var/run/redmine-robot.pid'
    self.pidfile_timeout = 5
  def run(self):
    info("Service started")
    redmine = Redmine()
    while True:
      redmine.scheduler()
      for i in range(5):
        redmine.execute()
        time.sleep(60)

app = App()
daemon_runner = runner.DaemonRunner(app)
daemon_runner.daemon_context.files_preserve=[handler.stream]
daemon_runner.do_action()
