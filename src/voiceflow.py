import requests
import uuid
from urllib.parse import urljoin

class MemoryStore:
  def __init__(self):
    self.store = None

  def get(self):
    return self.store

  def put(self, value):
    self.store = value

class Voiceflow:
  def __init__(self, apiKey, stateStore=MemoryStore):
    self.apiKey = apiKey
    self.stateStore = stateStore()
    self.url = "https://general-runtime.voiceflow.com"

  def clear_state(self):
    self.stateStore.put(None)

  def interact(self, versionID, input):
    # Get state
    state = self.stateStore.get()
    if state is None:
      state = self.initState(versionID)

    # Call interactions
    body = {
      "state": state,
      "request": {
        "type": 'text',
        "payload": input,
      },
      "config": {
        "tts": "true",
      },
    }
    response = requests.post(urljoin(self.url, "/interact/"+versionID), json=body, headers={"Authorization":self.apiKey}).json()

    # Save state
    self.stateStore.put(response["state"])

    # Return response
    return response

  def initState(self, versionID):
    # Generate a new user ID for each session so that different clients don't interfere with each other. 
    # For production implementations, this should be set once per device.
    tempUUID = str(uuid.uuid4())
    userID = "rpi_demo_"+tempUUID[len(tempUUID)-12:]
    print("New session user ID: " + userID)

    initialState = requests.get(urljoin(self.url, "/interact/"+versionID+"/state"), headers={"Authorization":self.apiKey}).json()

    response = requests.post(urljoin(self.url, "/interact/"+versionID), json=initialState, headers={"Authorization":self.apiKey}).json()
    return response["state"]
