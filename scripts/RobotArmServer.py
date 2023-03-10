#! /usr/bin/env python3

import roslib
roslib.load_manifest('eye_tracking_server')
import rospy
import actionlib
from controller import AcquisitionControl
import geometry_msgs
from time import sleep

import rospkg
PACKAGE_HOME = rospkg.RosPack().get_path('eye_tracking_server')

import pickle as pkl
import numpy as np
import copy

from moveit_msgs.msg import Constraints, OrientationConstraint


from region import AcquisitionRegion

# The eye_tracking_server.msg is placed under /catkin_ws/devel/shared/eye_tracking_server/msgs
from eye_tracking_server.msg import GoToAction

from eye_tracking_server.srv import nbOfPosition,nbOfPositionResponse


# Modules required by the get_key() function, used in the manual mode.
import os
import select
import sys
import termios
import tty

def get_key(settings):
  tty.setraw(sys.stdin.fileno())
  rlist, _, _ = select.select([sys.stdin], [], [], 0.1)
  if rlist:
    key = sys.stdin.read(1)
  else:
    key = ''

  termios.tcsetattr(sys.stdin, termios.TCSADRAIN, settings)
  return key

def pose2array(pose):
   return np.array([pose.position.x,pose.position.y,pose.position.z])
   
class GoToServer:
  def __init__(self,grid_d):
    
    # Initialize the waypoints to go to.

    # Assume the corners are already stored.
    fn = '{}/data/corners.pkl'.format(PACKAGE_HOME) 
    # or input('Please input the path to the .pkl file storing the corners[default:../data/corners.pkl]:')
    with open(fn,'rb') as f:
        data = pkl.load(f)
        corners = data['corner_poses']
        self.corner_joint_values = data['corner_joint_values']

    print('Corner coordinates are loaded from {}'.format(fn))
    print(corners)

    corner_pos = np.array([[c.position.x,c.position.y,c.position.z] for c in corners])
    aq_region = AcquisitionRegion(corner_pos)
    grid = aq_region.grid(grid_d)

    # Assume the side faces are already stored.
    side_faces_path = '{}/data/side_faces.pkl'.format(PACKAGE_HOME)
    with open(side_faces_path,'rb') as f:
      side = pkl.load(f)
    
    n_grid=len(grid)
    grid = np.vstack([grid,side])

    initial_wp = corners[0]
    waypoints = [copy.deepcopy(initial_wp) for _ in range(len(grid))]
    # The waypoints all have the same orientation as the first corner.
    # The positions of the waypoints are determined by the grid variable.
    for i in range(len(grid)):
        waypoints[i].position.x = grid[i,0]
        waypoints[i].position.y = grid[i,1]
        waypoints[i].position.z = grid[i,2]   


    waypoints = corners + waypoints


    self.waypoints = waypoints
    self.initial_wp = initial_wp  
    self.corners = corners
    
    print('Corners:{}, Side face points:{}, Grids:{}'.format(len(corners),len(side),n_grid))
    print('Total waypoints:{}'.format(len(self.waypoints)))
	
    # Initialized the robot controller
    self.controller = AcquisitionControl()
    

    self.scene = self.controller.scene

    # Initialize the action server.

    self.server = actionlib.SimpleActionServer('GoTo', GoToAction, self.goto, False)
    self.server.start()

    # Initialize the number of locations server.
    s = rospy.Service('nbOfPosition', nbOfPosition, self.handle_nbOfPosition)

    # Initialize the system settings required by get_key()
    self.key_settings = termios.tcgetattr(sys.stdin)

    self.manual_control_on = False

    # Adding the box representing the tablet.
    self.add_box()
    self.attach_box()
    self.add_table()


  def fix_eff_orientation_in_planning(self):
    self.controller.move_group.clear_path_constraints()
    curr_pose = self.controller.move_group.get_current_pose().pose


    # Adding the orientation constraint for the end factor.
    # We want the end factor to always face the same orientation as the initial waypoint.
    ocm = OrientationConstraint()
    ocm.link_name = self.controller.eef_link
    ocm.header.frame_id = self.controller.planning_frame 
    ocm.orientation.x = curr_pose.orientation.x
    ocm.orientation.y = curr_pose.orientation.y
    ocm.orientation.z = curr_pose.orientation.z
    ocm.orientation.w = curr_pose.orientation.w

    ocm.absolute_x_axis_tolerance = 0.1;
    ocm.absolute_y_axis_tolerance = 0.1;
    ocm.absolute_z_axis_tolerance = 0.1;
    ocm.weight = 1.0;

    constraints = Constraints()
    constraints.orientation_constraints.append(ocm)

    self.controller.move_group.set_path_constraints(constraints)

  def spin(self):
    self.stop()
    input('Press Enter to start the server.')
    print('The application is now running in server mode. Press "m" to enter manual mode. Press Ctrl+C to shutdown the server.')    
    while(1):
      key = get_key(self.key_settings)
      if key=='m':
        self.stop()
        print('Stopping the robot and entering manual control.')
        self.manual_control_on = True
        self.manual_control()
      else:
        if (key == '\x03'):
          self.stop()
          break
  def manual_control(self):
    '''
      The keyboard interaction interface when the server is running in manual mode.
    '''
    while(1):
      command = input('Go to corner(c), waypoint(w), or exit(e) manual mode?')
      
      if command == 'e':
        print('Exit manual mode and resuming server mode. Press "m" to enter manual mode again.')
        self.manual_control_on = False  
        break
      elif not command in ['c','w']:
        print('Command {} not recognized.'.format(command))
        
      elif command == 'c':
        idx = int(input('Input the index of the corner.'))
        self.__gotocorner(idx) 

      elif command == 'w':
          idx = int(input('Input the index of the waypoint.'))
          self.__gotowaypoint(idx)

  def handle_nbOfPosition(self,req):
      return nbOfPositionResponse(len(self.waypoints))
  
  def stop(self):
    self.controller.move_group.stop()

  def __gotopose(self,target_pose):
    move_group = self.controller.move_group
    curr_pose = move_group.get_current_pose().pose
    target_pose.orientation = curr_pose.orientation

    # We do not want to change the orientation of the target_pose.

    # The current pose MUST NOT be included in the waypoints.
    
    # self.fix_eff_orientation_in_planning()

    plan,_ = move_group.compute_cartesian_path([target_pose],0.01,0)
    success = move_group.execute(plan,wait=True)
    move_group.stop()
    
    # Ensure the target location is really reached.
    try:
    	total_tries = 10
    	for _ in range(total_tries):
    	     curr_pose = move_group.get_current_pose().pose
    	     
    	     tolerance = 0.1
    	     
    	     dist = np.linalg.norm(pose2array(curr_pose)-pose2array(target_pose))
    	     print('Distance to  target pose:{}'.format(dist))
    	     if dist<tolerance:
    	        break
    	     sleep(0.5)
    	     if _ == total_tries-1:
                print('Target not reached')   
    except KeyboardInterrupt:
    	print('Keyboard interrupt detected.')
    
    return success

  def __gotowaypoint(self,idx):
    move_group = self.controller.move_group
    
    if idx<=len(self.waypoints):
      print('Go to waypoint idx:{}/{}'.format(idx,len(self.waypoints)))

      target_pose = self.waypoints[idx]
      success = self.__gotopose(target_pose)
    else:
      print("waypoint index {} out of bounds.".format(idx))
      success = False

    return success

  def __gotocorner(self,idx):
    move_group = self.controller.move_group
    
    if idx<=len(self.corners):
      print('Go to corner idx:{}/{}'.format(idx,len(self.corners)))
      
      # success = move_group.go(self.corner_joint_values[idx], wait=True)

      target_pose = self.corners[idx]
      success = self.__gotopose(target_pose)
    else:
      print("Corner index {} out of bounds.".format(idx))
      success = False

    return success

  def goto(self, goal):

    '''
      When the server is not running in manual mode, it accepts action requests from the client
      through the GoTo action server.
    '''
    if self.manual_control_on:
      print('Request received but currently manual control is active. Not responding.')
      self.server.set_aborted()
    else:
      idx = goal.waypoint_idx
      move_group = self.controller.move_group
      
      if idx>=len(self.waypoints):
        self.server.set_aborted()
      else:
        # move_group.set_pose_target(self.waypoints[idx])
        # success = move_group.go(wait=True)
        
        success = self.__gotowaypoint(idx)
        if success:
          self.server.set_succeeded()
        else:
          self.server.set_aborted()
  def add_box(self, timeout=4):
        # Copy class variables to local variables to make the web tutorials more clear.
        # In practice, you should use the class variables directly unless you have a good
        # reason not to.
        box_name = self.controller.box_name
        scene = self.controller.scene

        drive_name = 'drive'

        ## Adding Objects to the Planning Scene
        ## ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
        ## First, we will create a box in the planning scene between the fingers:
        box_pose = geometry_msgs.msg.PoseStamped()
        box_pose.header.frame_id = self.controller.planning_frame
        box_pose.pose = self.controller.move_group.get_current_pose().pose

        ## Add the drive box
        drive_pose = geometry_msgs.msg.PoseStamped()
        drive_pose.header.frame_id = self.controller.planning_frame
        drive_pose.pose = self.controller.move_group.get_current_pose().pose


        ############### The far corners configuration ###############
        box_pose.pose.position.y = box_pose.pose.position.y - 0.08    


        drive_pose.pose.position.y = drive_pose.pose.position.y - 0.055
        drive_pose.pose.position.z = drive_pose.pose.position.z - 0.08
        

        scene.add_box(box_name, box_pose, size=(0.3, 0.25, 0.02))
        scene.add_box(drive_name, drive_pose, size=(0.09, 0.02, 0.02))
        



        ############## The close corners configuration###############
        # box_pose.pose.position.y = box_pose.pose.position.y - 0.05 # This is to place the tablet a few centimeters away from the actual flange.        
        # scene.add_box(box_name, box_pose, size=(0.5, 0.5, 0.02))

        
        self.box_name = box_name
        return self.wait_for_state_update(box_is_known=True, timeout=timeout)
  def add_table(self, timeout=4):
    # Copy class variables to local variables to make the web tutorials more clear.
    # In practice, you should use the class variables directly unless you have a good
    # reason not to.
    table_name = 'table'
    scene = self.controller.scene

    ## Adding Objects to the Planning Scene
    ## ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
    ## First, we will create a box in the planning scene between the fingers:
    table_pose = geometry_msgs.msg.PoseStamped()
    table_pose.header.frame_id = self.controller.planning_frame
    table_pose.pose.orientation.w = 1.0
    table_pose.pose.position.z = -1.01

    table_pose.pose.position.y = 0.90
    scene.add_box(table_name, table_pose, size=(2, 2, 2))

    return self.wait_for_state_update(box_is_known=True, timeout=timeout)


  def attach_box(self, timeout=4):
      box_name = self.controller.box_name
      drive_name = 'drive'
      robot = self.controller.robot
      scene = self.controller.scene
      eef_link = self.controller.eef_link
      group_names = self.controller.group_names

      touch_links = ['wrist_1_link','wrist_2_link','wrist_3_link'] 
      # The box is allowed to touch the three wrist links, and not allowed to touch the remaining links, like forarm_link
      

      # touch_links = [] # The box is not allowed to touch any links.
      scene.attach_box(eef_link, box_name, touch_links=touch_links)
      scene.attach_box(eef_link, drive_name, touch_links=[])


      return self.wait_for_state_update(
          box_is_attached=True, box_is_known=False, timeout=timeout
      )

  def detach_box(self, timeout=4):
     
      box_name = self.controller.box_name
      scene = self.controller.scene
      eef_link = self.controller.eef_link

    
      scene.remove_attached_object(eef_link, name=box_name)
      
      return self.wait_for_state_update(
          box_is_known=True, box_is_attached=False, timeout=timeout
      )

  def remove_box(self, timeout=4):
     
      box_name = self.controller.box_name
      scene = self.controller.scene

     
      scene.remove_world_object(box_name)

      return self.wait_for_state_update(
          box_is_attached=False, box_is_known=False, timeout=timeout
      )
  def wait_for_state_update(
      self, box_is_known=False, box_is_attached=False, timeout=4
  ):
      box_name = self.controller.box_name
      scene = self.controller.scene

    
      start = rospy.get_time()
      seconds = rospy.get_time()
      while (seconds - start < timeout) and not rospy.is_shutdown():
          # Test if the box is in attached objects
          attached_objects = scene.get_attached_objects([box_name])
          is_attached = len(attached_objects.keys()) > 0

          # Test if the box is in the scene.
          # Note that attaching the box will remove it from known_objects
          is_known = box_name in scene.get_known_object_names()

          # Test if we are in the expected state
          if (box_is_attached == is_attached) and (box_is_known == is_known):
              return True

          # Sleep so that we give other threads time on the processor
          rospy.sleep(0.1)
          seconds = rospy.get_time()

      # If we exited the while loop without returning then we timed out
      return False
      ## END_SUB_TUTORIAL
if __name__ == '__main__':
  rospy.init_node('GoToServer')
  grid_d = 0.05
  
  server = GoToServer(grid_d)
  server.spin()
