# eye_tracking_server
The ROS 1 repository for automatic eye tracking acquisition using a robotic arm.

# Installation
Clone this package to the src/ folder of your catkin workspace, then build the package.

```bash
  $ cd ~/catkin_ws/src
  $ git clone https://github.com/lina-robotics-lab/eye_tracking_server.git
  $ cd ~/catkin_ws
  $ rosdep install --from-paths src --ignore-src -r -y
  $ catkin build eye_tracking_server
```

# Step 1: record the corner coordinates.
First, bring up the real robot or simulated robot, then run the MoveIt! interface.

Source the ROS workspace, then run 

```bash
  $ rosrun eye_tracking_server RecordCorners.py
```

Follow the prompts to record the coordinates of the corners of the 3-D acquisition region.


# Step 2: run the server.

First, bring up the real robot or simulated robot, then run the MoveIt! interface.

Source the ROS workspace, then run 

```bash
  $ rosrun eye_tracking_server RobotArmServer.py
```

Alternatively, 

```bash
  $ cd ~/catkin_ws/src/eye_tracking_server/scripts
  $ python3 RobotArmServer.py
```

Then the application will be up and ready to receive requests from the client.

The application can operate under two modes: server mode and manual mode. By default, the application will be running in server mode. Under this mode, the application only serves as a server that interacts with the client via ROS. 

By pressing 'm' in server mode, the application will switch to manual mode. Under this mode, the application no longer accepts requests from the client, but directly interacts with the user via keyboard commands. Follow the prompt to control the robot to go to different waypoints or corners. Press 'e' to exit the manual mode and return to server mode.
