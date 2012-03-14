#! /usr/bin/python
# -*- coding: UTF-8 -*-
__author__      = "Tonio Gsell <tgsell@tik.ee.ethz.ch>"
__copyright__   = "Copyright 2010, ETH Zurich, Switzerland, Tonio Gsell"
__license__     = "GPL"
__version__     = "$Revision$"
__date__        = "$Date$"
__id__          = "$Id$"
__source__      = "$URL$"

import logging
import Queue
import os
import shutil
import time
import thread
from threading import Thread, Event, Lock, Timer

from ScheduleHandler import SUBPROCESS_BUG_BYPASS
if SUBPROCESS_BUG_BYPASS:
    import SubprocessFake
    subprocess = SubprocessFake
else:
    import subprocess

import BackLogMessage
from AbstractPlugin import AbstractPluginClass

try: 
    import serial
except ImportError, e: 
    print "Please install PySerial first."
    sys.exit(1)

DEFAULT_BACKLOG = True
GPHOTO2 = '/usr/bin/gphoto2'
TMPPICTUREFOLDER = '/media/card/backlog/binaryplugin/tmp/'
POSTFIX='.%C'
DEFAULT_GPHOTO2_SETTINGS = ['/main/capturesettings/evstep=0',
                            '/main/imgsettings/imagequality=0',
                            '/main/imgsettings/imagesize=2',
                            '/main/imgsettings/whitebalance=0',
                            '/main/capturesettings/exposurecompensation=15',
                            '/main/capturesettings/expprogram=1',
                            '/main/imgsettings/autoiso=0',
                            '/main/capturesettings/bracketing=1',
                            '/main/capturesettings/burstinterval=0']

TASK_MESSAGE = 0
POWER_MESSAGE = 1

PANORAMA_TASK = 0
PICTURE_TASK = 1
POSITIONING_TASK = 2
MODE_TASK = 3
CALIBRATION_TASK = 4

class CamZillaPluginClass(AbstractPluginClass):
    '''
    This plugin offers the functionality to control the CamZilla robot.
    '''

    '''
    data/instance attributes:
    _manualControl
    _x
    _y
    _parkX
    _parkY
    _power
    _calibrated
    _delay
    _writeLock
    _pulsesPerDegree
    _taskqueue
    _plugStop
    _isBusy
    '''
    
    def __init__(self, parent, config):
        AbstractPluginClass.__init__(self, parent, config, DEFAULT_BACKLOG, needPowerControl=True)
        self._isBusy = True
        
        self._serial = serial.Serial()
        self._taskqueue = Queue.Queue()
        self._delay = Event()
        self._parkTimer = None
        self._parkActionLock = Lock()
        self._writeLock = Lock()
        self._manualControl = True
        self._plugStop = False
        self._power = False
        self._calibrated = False
        self._x = 0
        self._y = 0
        self._parkX = 0
        self._parkY = 0
        self._autofocus = None
        
        device = self.getOptionValue('device_name')
        if device is None:
            raise TypeError('no device_name specified')
        
        value = self.getOptionValue('pulses_per_degree')
        if value is None:
            raise TypeError('no pulses_per_degree value specified')
        else:
            self._pulsesPerDegree = float(value)
        
        value = self.getOptionValue('park_robot_idle_time')
        if value is None:
            raise TypeError('no park_robot_idle_time value specified')
        else:
            self._parkIdleTime = float(value)*60
        
        value = self.getOptionValue('park_position')
        if value is None:
            self.warning('no park_position value specified')
        else:
            s = value.strip().split('/')
            self._x = self._parkX = float(s[0])
            self._y = self._parkY = float(s[1])
            
        self.info('encoder pulses per degree: %f' % (self._pulsesPerDegree,))
        self.info('using device %s' % (device,))
        self._serial.setPort(device)
            
        if not os.path.exists(GPHOTO2):
            raise TypeError('%s does not exist' % (GPHOTO2,))
        if not os.access(GPHOTO2, os.X_OK):
            raise TypeError('%s can not be executed' % (GPHOTO2,))
        
        if self.getPowerControlObject().getUsb3Status():
            self.info('USB3 port is turned on')
        else:
            self.info('USB3 port is turned off')
        
        if self.getPowerControlObject().getExt1Status():
            self.info('robot and photo camera is turned on')
        else:
            self.info('robot and photo camera is turned off')
        
        self._pictureFolder = self.getOptionValue('picture_folder')
        if self._pictureFolder is None:
            raise TypeError('no picture_folder specified')
        if not os.path.isdir(self._pictureFolder):
            self.warning('picture folder >%s< is not a directory -> creating it' % (self._pictureFolder,))
            os.makedirs(self._pictureFolder)
        
        value = self.getOptionValue('power_save_mode')
        self._powerSaveMode = False
        if value != None and int(value) == 1:
            self.info('power save mode is turned on')
            self._powerSaveMode = True
        else:
            self.info('power save mode is turned off')
            self._startupRobotAndCam()
    
    
    def getMsgType(self):
        return BackLogMessage.CAMZILLA_MESSAGE_TYPE
        
        
    def isBusy(self):
        return self._isBusy
        
        
    def needsWLAN(self):
        return False
    
    
    def msgReceived(self, data):
        try:
            thread.start_new_thread(self._parseMsg, (data,))
        except Exception, e:
            self.exception(e)
       
        
    def run(self):
        self.name = 'CamZillaPlugin-Thread'
        self.info('started')
        
        if not self._powerSaveMode and not self._calibrated:
            try:
                self._calibrateRobot()
            except Exception, e:
                self.exception(e)
            if self._taskqueue.empty():
                try:
                    self._parkRobot()
                except Exception, e:
                    self.exception(str(e))
            
        if not self._plugStop and not self._powerSaveMode:
            try:
                self._downloadUnknownPictures()
            except Exception, e:
                self.error(e.__str__())

        while not self._plugStop:
            if self._taskqueue.empty():
                self._isBusy = False
            task = self._taskqueue.get()
            
            if self._parkTimer is not None:
                try:
                    self._parkTimer.cancel()
                except Exception, e:
                    self.exception(str(e))
            self._parkActionLock.acquire()
            
            self._isBusy = True
            if self._plugStop:
                try:
                    self._taskqueue.task_done()
                except ValueError, e:
                    self.exception(e)
                break
            
            try:
                now = time.time()
                if task[0] == PANORAMA_TASK:
                    if self._powerSaveMode:
                        self._startupRobotAndCam()
                        if not self._calibrated:
                            self._calibrateRobot()
                    
                    if not self._plugStop:
                        try:
                            self._downloadUnknownPictures()
                        except Exception, e:
                            self.error(e.__str__())
                    
                        if not self._plugStop:
                            now = time.time()
                            
                            try:
                                parsedTask = self._parseTask(task[1])
                            except Exception, e:
                                if not self._plugStop:
                                    self.error(e.__str__())
                                    self.processMsg(self.getTimeStamp(), [int(now*1000)] + ['panorama', 'could not execute task: %s' % (e.__str__(),), self._x,self._y] + [None]*9)
                            else:
                                self.info('executing panorama picture task: start(%s,%s) pictures(%s,%s) rotation(%s,%s) delay(%s) batch(%s) gphoto2(%s)' % (str(parsedTask[0]), str(parsedTask[1]), str(parsedTask[2]), str(parsedTask[3]), str(parsedTask[4]), str(parsedTask[5]), str(parsedTask[6]), str(parsedTask[7]), str(parsedTask[8])))
                                pic_name_list = []
                                
                                if self._power:
                                    pic = 1
                                    try:
                                        config, bracketing = self._configureCamera(parsedTask[8])
                                        y = parsedTask[1]
                                        while y < parsedTask[1]+(parsedTask[3]*parsedTask[5]) and not self._plugStop:
                                            ret = self._position(y=y)
                                            yLimit = ret[3]
                                            x = parsedTask[0]
                                            
                                            while x < parsedTask[0]+(parsedTask[2]*parsedTask[4]) and not self._plugStop:
                                                ret = self._position(x=x)
                                                xLimit = ret[3]
                                                if parsedTask[6] > 0:
                                                    self._delay.wait(parsedTask[6])
                                                if not self._plugStop:
                                                    if bracketing:
                                                        self.info('taking pictures number %d-%d/%d at position (%f,%f)' % (1+(pic-1)*3,3+(pic-1)*3,parsedTask[2]*parsedTask[3]*3,self._x,self._y))
                                                    else:
                                                        self.info('taking picture number %d/%d at position (%f,%f)' % (pic,parsedTask[2]*parsedTask[3],self._x,self._y))
                                                    self._takePicture()
                                                    if not self._plugStop:
                                                        s = 'successfully'
                                                        if (xLimit is True and yLimit is True):
                                                            s += ' (reached x and y limit)'
                                                        elif (xLimit is True and yLimit is False):
                                                            s += ' (reached x limit)'
                                                        elif (xLimit is False and yLimit is True):
                                                            s += ' (reached y limit)'
                                                            
                                                        if bracketing:
                                                            if parsedTask[7] == 0:
                                                                l = []
                                                                for i in range(3):
                                                                    l.append('%s_pic%.3d_%dx_%dy_bracket%d.%s' % (time.strftime('%Y%m%d_%H%M%S', time.gmtime(now)), pic, int(round(self._x*10)), int(round(self._y*10)), i+1, '%C'))
                                                                self._downloadPictures(l)
                                                            else:
                                                                for i in range(3):
                                                                    pic_name_list.append('%s_pic%.3d_%dx_%dy_bracket%d.%s' % (time.strftime('%Y%m%d_%H%M%S', time.gmtime(now)), pic, int(round(self._x*10)), int(round(self._y*10)), i+1, '%C'))
                                                            self.processMsg(self.getTimeStamp(), [int(now*1000)] + ['panorama', 'pictures number %d-%d/%d taken %s'  % (1+(pic-1)*3, 3+(pic-1)*3, parsedTask[2]*parsedTask[3]*3, s), self._x,self._y] + parsedTask[:-1] + [config])
                                                        else:
                                                            pic_str = '%s_pic%.3d_%dx_%dy.%s' % (time.strftime('%Y%m%d_%H%M%S', time.gmtime(now)), pic, int(round(self._x*10)), int(round(self._y*10)), '%C')
                                                            if parsedTask[7] == 0:
                                                                self._downloadPictures([pic_str])
                                                            else:
                                                                pic_name_list.append(pic_str)
                                                            self.processMsg(self.getTimeStamp(), [int(now*1000)] + ['panorama', 'picture number %d/%d taken %s' % (pic, parsedTask[2]*parsedTask[3], s), self._x,self._y] + parsedTask[:-1] + [config])
                                                        pic += 1
                    
                                                        x += parsedTask[4]
                                                
                                            y += parsedTask[5]
                                            
                                        if parsedTask[7] != 0:
                                            self._downloadPictures(pic_name_list)
                                    except Exception, e:
                                        if not self._plugStop:
                                            self.processMsg(self.getTimeStamp(), [int(now*1000)] + ['panorama', 'could not finish task successfully (%s)' % (e.__str__(),), self._x, self._y] + parsedTask[:-1] + [config])
                                            self.error(e.__str__())
                                    else:
                                        if not self._plugStop:
                                            self.info('all pictures taken successfully')
                                            self.processMsg(self.getTimeStamp(), [int(now*1000)] + ['panorama', 'finished successfully', self._x, self._y] + parsedTask[:-1] + [config])
                                            self.info('panorama picture task finished successfully')
                                else:
                                    self.processMsg(self.getTimeStamp(), [int(now*1000)] + ['panorama', 'CamZilla is not powered -> turn power on first', self._x,self._y] + [None]*9)
                                    self.error('CamZilla is not powered -> turn power on first')
                elif task[0] == PICTURE_TASK:
                    self.info('picture now task received -> taking picture(s) in current robot position (x=%f,y=%f)' % (self._x, self._y))
    
                    if self._powerSaveMode and not self._plugStop:
                        self._startupRobotAndCam()
                    
                    try:
                        self._downloadUnknownPictures()
                    except Exception, e:
                        self.error(e.__str__())
                        
                    if not self._plugStop:
                        now = time.time()
                            
                        if task[1]:
                            gphoto2conf = task[1].split(',')
                        else:
                            gphoto2conf = []
                        
                        if not self._plugStop:
                            try:
                                config, bracketing = self._configureCamera(gphoto2conf)
                                self.info('taking picture(s) now')
                                self._takePicture()
                            except Exception, e:
                                if not self._plugStop:
                                    self.processMsg(self.getTimeStamp(), [int(now*1000)] + ['picture_now', 'could not take picture now (%s)' % (e.__str__(),), self._x, self._y] + [None]*8 + [config])
                                    self.error(e.__str__())
                            else:
                                if not self._plugStop:
                                    try:
                                        if bracketing:
                                            l = []
                                            for i in range(3):
                                                l.append('%s_pic001_%dx_%dy_bracket%d.%s' % (time.strftime('%Y%m%d_%H%M%S', time.gmtime(now)), int(round(self._x*10)), int(round(self._y*10)), i+1, '%C'))
                                            self._downloadPictures(l)
                                        else:
                                            self._downloadPictures(['%s_pic001_%dx_%dy.%s' % (time.strftime('%Y%m%d_%H%M%S', time.gmtime(now)), int(round(self._x*10)), int(round(self._y*10)), '%C')])
                                    except Exception, e:
                                        if not self._plugStop:
                                            self.processMsg(self.getTimeStamp(), [int(now*1000)] + ['picture_now', 'could not download all pictures (%s)' % (e.__str__(),), self._x, self._y] + [None]*8 + [config])
                                            self.error(e.__str__())
                                    else:
                                        if not self._plugStop:
                                            self.processMsg(self.getTimeStamp(), [int(now*1000)] + ['picture_now', 'finished successfully', self._x, self._y] + [None]*8 + [config])
                                            self.info('picture now task finished successfully')
                elif task[0] == POSITIONING_TASK:
                    self.info('positioning task received (x=%f,y=%f)' % (task[1], task[2]))
                    if self._powerSaveMode:
                        self._startupRobotAndCam()
                        if not self._calibrated:
                            self._calibrateRobot()
                            
                    try:
                        pos = self._position(x=task[1], y=task[2])
                    except Exception, e:
                        if not self._plugStop:
                            self.processMsg(self.getTimeStamp(), [int(now*1000)] + ['positioning', 'not finished successfully (%s)' % (e.__str__(),), self._x, self._y] + [None]*9)
                            self.error(e.__str__())
                    else:
                        if not self._plugStop:
                            s = 'finished successfully'
                            if (pos[2] is True and pos[3] is True):
                                s += ' (reached x and y limit)'
                            elif (pos[2] is True and pos[3] is False):
                                s += ' (reached x limit)'
                            elif (pos[2] is False and pos[3] is True):
                                s += ' (reached y limit)'
                            self.processMsg(self.getTimeStamp(), [int(now*1000)] + ['positioning', s, self._x, self._y] + [None]*9)
                            self.info('positioning task %s' % (s,))
                elif task[0] == MODE_TASK:
                    if self._power:
                        if task[1] == 0:
                            self.info('mode task received from GSN >joystick off<')
                            self._write("j=off")
                            self.processMsg(self.getTimeStamp(), [int(now*1000)] + ['mode', 'joystick turned off', self._x, self._y] + [None]*9)
                        elif task[1] == 1:
                            self.info('mode task received from GSN >joystick on<')
                            self._write("j=on")
                            self.processMsg(self.getTimeStamp(), [int(now*1000)] + ['mode', 'joystick turned on', self._x, self._y] + [None]*9)
                        else:
                            self.processMsg(self.getTimeStamp(), [int(now*1000)] + ['mode', 'unknown mode', self._x, self._y] + [None]*9)
                            self.error('unknown mode task received from GSN')
                    else:
                        self.processMsg(self.getTimeStamp(), [int(now*1000)] + ['mode', 'CamZilla is not powered -> turn power on first', self._x, self._y] + [None]*9)
                        self.error('CamZilla is not powered -> turn power on first')
                elif task[0] == CALIBRATION_TASK:
                    if self._power:
                        self.info('calibration task received from GSN -> calibrate robot')
                    self._calibrateRobot()
            except Exception, e:
                self.exception(str(e))
                
            try:
                self._taskqueue.task_done()
            except ValueError, e:
                self.exception(e)
            self._parkActionLock.release()
            
            if self._taskqueue.empty() and not self._plugStop:
                self._parkTimer = Timer(self._parkIdleTime, self._parkAction)
                self._parkTimer.start()
        
        self.info('died')


    def action(self, parameters):
        if isinstance(parameters, str):
            self._taskqueue.put([PANORAMA_TASK, parameters])
        else:
            self._taskqueue.put(parameters)
    
    
    def stop(self):
        self._isBusy = False
        self._plugStop = True
        self._delay.set()
        self._taskqueue.put('end')
        self.join()
        self._parkRobot()
        self._shutdownRobotAndCam()
        
        
    def _parkAction(self):
        self._parkActionLock.acquire()
        now = self.getTimeStamp()
        try:
            self._parkRobot()
        except Exception, e:
            self.exception(str(e))
        if self._powerSaveMode:
            try:
                self._shutdownRobotAndCam()
            except Exception, e:
                self.exception(str(e))
        
        self._parkActionLock.release()
        log_str = 'CamZilla has been parked successfully after being idle for %f minutes' % (self._parkIdleTime/60,)
        self.processMsg(now, [now] + ['parking', log_str, self._x, self._y] + [None]*9)
        self.info(log_str)
            
            
    def _parseMsg(self, data):
        if data[0] == TASK_MESSAGE:
            self.info('new task message received from GSN')
            self.action(data[1:])
        elif data[0] == POWER_MESSAGE:
            now = time.time()
            self.info('power message received from GSN')
            if data[1] == 0:
                self.info('turn robot and camera off')
                log_str = 'Camera and robot are turned off'
                self._shutdownRobotAndCam()
            elif data[1] == 1:
                self.info('turn robot and camera on')
                try:
                    self._startupRobotAndCam()
                    log_str = 'Camera and robot are turned on'
                except TypeError, e:
                    self.error(str(e))
            else:
                self.error('unknown robot and camera message received from GSN')
                
            heater = None
            if data[2] == 0:
                self.info('turn heater off')
                log_str += ' and heater is turned off'
                self.getPowerControlObject().ext3Off()
                heater = False
            elif data[2] == 1:
                self.info('turn heater on')
                log_str += ' and heater is turned on'
                self.getPowerControlObject().ext3On()
                heater = True
            else:
                self.error('unknown heater message received from GSN')
                
            self.processMsg(self.getTimeStamp(), [int(now*1000)] + ['power', log_str, self._x, self._y] + [None]*9)
        else:
            self.error('unknown message type received from GSN')
        
        
    def _parseTask(self, task):
        params = task.strip().split(' ')
        ret = [None]*9
        for param in params:
            p = param.lower()
            if p.startswith('start'):
                startX, startY = param[6:-1].split(',')
                ret[0] = float(startX)
                ret[1] = float(startY)
            elif p.startswith('pictures'):
                picsX, picsY = param[9:-1].split(',')
                ret[2] = int(picsX)
                ret[3] = int(picsY)
            elif p.startswith('rotation'):
                rotationX, rotationY = param[9:-1].split(',')
                ret[4] = float(rotationX)
                ret[5] = float(rotationY)
            elif p.startswith('delay'):
                ret[6] = int(param[6:-1])
            elif p.startswith('batch'):
                ret[7] = int(param[6:-1])
            elif p.startswith('gphoto2'):
                ret[8] = param[8:-1].split(',')
            else:
                self.error('unrecognized parameter >%s< in task >%s<' % (param,task))
        if ret[0] is None:
            ret[0] = 0.0
        if ret[1] is None:
            ret[1] = 0.0
        if ret[2] is None:
            ret[2] = 1
        if ret[3] is None:
            ret[3] = 1
        if ret[4] is None and ret[2] > 1:
            raise TypeError('x-rotation has to be specified if more than one picture has to be taken in x-direction')
        if ret[5] is None and ret[3] > 1:
            raise TypeError('y-rotation has to be specified if more than one picture has to be taken in y-direction')
        if ret[4] is None:
            ret[4] = 1.0
        if ret[5] is None:
            ret[5] = 1.0
        if ret[6] is None:
            ret[6] = 0
        if ret[7] is None:
            ret[7] = 1
        if ret[8] is None:
            ret[8] = []
        return ret
    
    
    
    def _configureCamera(self, settings):
        self.info('configure camera')
        configlist = []
        
        for default in DEFAULT_GPHOTO2_SETTINGS:
            notavailable = True
            def_begin = default.split('=')[0].strip()
            for setting in settings:
                if def_begin == setting.split('=')[0].strip():
                    notavailable = False
                    break
            if notavailable:
                settings.insert(0, default)
        
        sets = []
        ret = '/main/settings/capturetarget=1'
        self._autofocus = None
        for setting in settings:
            ret += ', ' + setting
            if setting.find('/main/actions/autofocusdrive') != -1:
                self._autofocus = '--set-config %s' % (setting.strip(),)
            elif setting.find('/main/actions/manualfocusdrive') != -1:
                self._setFocus(setting)
            else:
                sets.append('--set-config-index %s' % (setting.strip(),))
            
        bracketing = False
        if ret.find('bracketing=0') != -1:
            bracketing = True
        command = [GPHOTO2, '--port="usb:"', '--quiet'] + sets
        self._execCommand(command)
        return ret.strip(), bracketing
        
        
    def _takePicture(self):
        if self._autofocus:
            #command = [GPHOTO2, '--port="usb:"', '--force-overwrite', '--quiet', '--set-config-index /main/settings/capturetarget=1', self._autofocus, '--capture-image']
            command = [GPHOTO2, '--port="usb:"', '--force-overwrite', '--quiet', self._autofocus, '--capture-image']
        else:
            #command = [GPHOTO2, '--port="usb:"', '--force-overwrite', '--quiet', '--set-config-index /main/settings/capturetarget=1', '--capture-image']
            command = [GPHOTO2, '--port="usb:"', '--force-overwrite', '--quiet', '--capture-image']
        self._execCommand(command)
        
        
    def _setFocus(self, focus):
        command = [GPHOTO2, '--port="usb:"', '--force-overwrite', '--quiet', '--capture-preview', '--set-config /main/actions/manualfocusdrive=32767', '--set-config %s' % (focus,)]
        self._execCommand(command)
        
        
    def _downloadPictures(self, filenames):
        self.info('downloading all pictures from photo camera')
        if not os.path.isdir(TMPPICTUREFOLDER):
            os.makedirs(TMPPICTUREFOLDER)
        if os.listdir(TMPPICTUREFOLDER):
            self.warning('there are still files in the temporary directory -> move them to %s' % (self._pictureFolder,))
            for file in sorted(os.listdir(TMPPICTUREFOLDER)):
                shutil.move(os.path.join(TMPPICTUREFOLDER, file), self._pictureFolder)
               
        pic_count = 0
        for filename in filenames:
            if self._plugStop:
                break
            self._execCommand([GPHOTO2, '--port="usb:"', '--quiet', '--get-file=1', '--filename=' + filename, '--recurse', '--delete-file=1'], TMPPICTUREFOLDER)
            bugwait=5
            for file in os.listdir(TMPPICTUREFOLDER):
                file = os.path.join(TMPPICTUREFOLDER, file)
                bugwait = os.path.getsize(file) / 500000
                shutil.move(file, self._pictureFolder)
            self._delay.wait(bugwait)
            pic_count += 1
        if pic_count > 0:
            self.info('downloaded %d pictures from photo camera' % (pic_count,))

        os.rmdir(TMPPICTUREFOLDER)
        
        
    def _downloadUnknownPictures(self):
        self.info('downloading all unknown pictures from photo camera')
        if not os.path.isdir(TMPPICTUREFOLDER):
            os.makedirs(TMPPICTUREFOLDER)
        if os.listdir(TMPPICTUREFOLDER):
            self.warning('there are still files in the temporary directory -> move them to %s' % (self._pictureFolder,))
            for file in sorted(os.listdir(TMPPICTUREFOLDER)):
                shutil.move(os.path.join(TMPPICTUREFOLDER, file), self._pictureFolder)
               
        pic_count = 0
        filename_time = time.strftime('%Y%m%d_%H%M%S', time.gmtime(time.time()))
        ret = self._execCommand([GPHOTO2, '--port="usb:"', '--quiet', '--list-files'], stdOutput = False)
        for line in ret[0].splitlines():
            if line.find('DSC_') != -1 and not self._plugStop:
                pic_count += 1
                self._execCommand([GPHOTO2, '--port="usb:"', '--quiet', '--get-file=1', '--filename=%s_pic%.3d_unknown.%s' % (filename_time,pic_count,'%C'), '--recurse', '--delete-file=1'], TMPPICTUREFOLDER)
                bugwait=5
                for file in os.listdir(TMPPICTUREFOLDER):
                    file = os.path.join(TMPPICTUREFOLDER, file)
                    bugwait = os.path.getsize(file) / 500000
                    shutil.move(file, self._pictureFolder)
                self._delay.wait(bugwait)
        if pic_count > 0:
            self.info('downloaded %d unknown pictures from photo camera' % (pic_count,))

        os.rmdir(TMPPICTUREFOLDER)
        
        
        
    def _execCommand(self, params, cwd=None, stdOutput=True):
        p = subprocess.Popen(params, stdout=subprocess.PIPE, stderr=subprocess.PIPE, cwd=cwd)
        ret = p.wait()
        output = p.communicate()
        if output[0] and stdOutput:
            self.info(output[0])
        if ret == 0:
            if output[1]:
                self.warning(output[1])
        else:
            if self._power:
                if output[1]:
                    self.error(output[1])
            else:
                raise Exception('camera has no more power -> gphoto2 could not execute command')
        return output
            
            
    def _parkRobot(self):
        if self._power:
            self._position(self._parkX, self._parkY)
    
    
    def _shutdownRobotAndCam(self):
        if self._power:
            if self._serial.isOpen():
                self._serial.close()
            self._power = False
            # turn the USB2 port off
            self.getPowerControlObject().usb2Off()
            # turn the USB3 port off
            self.getPowerControlObject().usb3Off()
            # turn the robot and photo camera off
            self.getPowerControlObject().ext1Off()
            self._calibrated = False
            return True
        
        self.getPowerControlObject().ext3Off()
        
        return False
        
    
    def _startupRobotAndCam(self):
        if not self._power:
            self.info('wait for robot to startup')
            # turn the USB2 port on
            self.getPowerControlObject().usb2On()
            # turn the USB3 port on
            self.getPowerControlObject().usb3On()
            # turn the robot and photo camera on
            self.getPowerControlObject().ext1On()
            self._power = True
            
            if not self._serial or not self._serial.isOpen():
                connect_cnt = 0
                while not self._plugStop:
                    try:
                        self._serial.open()
                    except serial.SerialException, e:
                        if connect_cnt == 5:
                            raise TypeError('could not initialize serial source: %s' % (e,))
                    else:
                        ans_cnt = 0
                        while not self._plugStop:
                            ans = self._serial.readline()
                            i = ans.rfind('Joystick')
                            if i != -1:
                                self.info(ans[i:])
                                self.info('robot ready')
                                return True
                            else:
                                self.warning('unexpected output received from arduino -> try again')
                            if ans_cnt >= 3:
                                raise TypeError('Arduino did not startup properly')
                            ans_cnt += 1
                    self._delay.wait(0.5)
                    connect_cnt += 1
                    
        return False
        
        
    def _calibrateRobot(self):
        now = self.getTimeStamp()
        if self._power:
            self._write("j=off")
            cal = self._write("cal")
            self._calibrated = True
            xmax = cal[0] * 2 / self._pulsesPerDegree
            ymax = cal[1] * 2 / self._pulsesPerDegree
            self._x = cal[2] / self._pulsesPerDegree
            self._y = cal[3] / self._pulsesPerDegree
            
            log_str = ''
            if xmax != 0 and ymax != 0:
                 log_str = ' (maximal rotation in degrees: x=%f, y=%f)' % (xmax,ymax)
            self.processMsg(now, [now] + ['calibration', 'finished successfully' + log_str, self._x, self._y] + [None]*9)
            self.info('calibration finished successfully' + log_str)
        else:
            self.error('robot not powered -> can not calibrate')
            self.processMsg(now, [now] + ['calibration', 'CamZilla is not powered -> turn power on first', self._x, self._y] + [None]*9)
            
            
    def _position(self, x=None, y=None):
        ret = [None]*4
        if x is not None and x != self._x:
            tmp = self._write('x=%d' % (int(round(x*self._pulsesPerDegree)),))
            self._x = tmp[0] / self._pulsesPerDegree
            ret[0] = self._x
            ret[2] = tmp[2]
        if y is not None and y != self._y:
            tmp = self._write('y=%d' % (int(round(y*self._pulsesPerDegree)),))
            self._y = tmp[1] / self._pulsesPerDegree
            ret[1] = self._y
            ret[3] = tmp[3]
        return ret
        
        
        
    def _write(self, com):
        try:
            self._writeLock.acquire()
            self.debug('servo control write: %s' % (com,))
            if com == 'j=on' or com == 'j=off':
                self._serial.write(com + "\n")
                ans = self._serial.readline().strip()
                self.debug('servo control answer: j=..: %s' % (ans,))
                if com != ans:
                    raise Exception('return value (%s) does not match command (%s)' % (ans, com))
                self._manualControl = (com == 'j=on')
            elif self._manualControl:
                raise Exception('manual joystick control is turned on -> command (%s) will not be executed' % (com,))
            elif com == 'cal':
                self._serial.write(com + "\n")
                cal1 = self._serial.readline().strip()
                self.debug('servo control answer: cal(1): %s' % (cal1))
                if cal1 == 'j=on':
                    self._manualControl = True
                    raise Exception('manual joystick control has been turned on -> no more commands will be sent to CamZilla until joystick control has been turned off')
                elif cal1 == '!cal':
                    raise Exception('could not calibrate')
                elif cal1.lower().find('emergency') != -1:
                    raise Exception('could not calibrate (answer: %s)' % (cal1))
                cal2 = self._serial.readline().strip()
                self.debug('servo control answer: cal(2): %s' % (cal2))
                cal1 = cal1[5:-1].split(',')
                cal2 = cal2.split('=')[1].split('/')
                return (int(cal1[0]), int(cal1[1]), int(cal2[0]), int(cal2[1]))
            elif com.startswith('x=') or com.startswith('y='):
                self._serial.write(com + "\n")
                ans = self._serial.readline().strip()
                self.debug('servo control answer: x=..: %s' % (ans,))
                if ans == '!cal':
                    raise Exception('not yet calibrated')
                elif ans.startswith('x/y='):
                    spl = ans.split('=')[1].split('/')
                    xLimit = yLimit = False
                    if (spl[0].endswith('L')):
                        spl[0] = spl[0][:-1]
                        xLimit = True
                    if (spl[1].endswith('L')):
                        spl[1] = spl[1][:-1]
                        yLimit = True
                    return (int(spl[0]), int(spl[1]), xLimit, yLimit)
                elif ans == 'j=on':
                    self._manualControl = True
                    raise Exception('manual joystick control has been turned on -> no more commands will be sent to CamZilla until joystick control has been turned off')
                elif ans.lower().find('emergency') != -1:
                    raise Exception(ans)
                else:
                    raise Exception('unknown return value for command (%s): %s' % (com, ans))
            else:
                raise TypeError('command (%s) unknown' % (com,))
        except Exception, e:
            raise e
        finally:
            self._writeLock.release()
            
    


if __name__ == '__main__':
    import signal
    import ConfigParser
    import optparse
    import logging.config

    class GSNPeerDummy():
        def processMsg(self, msgType, timestamp, payload, priority, backlog=False):
            pass
    class MainDummy():
        def __init__(self):
            self.gsnpeer = GSNPeerDummy()
            self.duty_cycle_mode = False
        def incrementExceptionCounter(self):
            pass
        def incrementErrorCounter(self):
            pass
        def runPluginRemoteAction(self):
            pass
    
    parser = optparse.OptionParser('usage: %prog [options]')
    
    parser.add_option('-c', '--config', type='string', dest='config_file', default='/etc/backlog.cfg',
                      help='Configuration file. Default: /etc/backlog.cfg', metavar='FILE')
    parser.add_option('-x', '--startx', type='int', dest='startX', default=0,
                      help='Lower-left horizontal starting point', metavar='INT')
    parser.add_option('-y', '--starty', type='int', dest='startY', default=0,
                      help='Lower-left vertical starting point', metavar='INT')
    parser.add_option('--picsx', type='int', dest='picturesX', default=1,
                      help='Number of pictures taken horizontally', metavar='INT')
    parser.add_option('--picsy', type='int', dest='picturesY', default=1,
                      help='Number of pictures taken vertically', metavar='INT')
    parser.add_option('--rotx', type='int', dest='rotationX', default=1,
                      help='Horizontal rotation in degrees between pictures', metavar='INT')
    parser.add_option('--roty', type='int', dest='rotationY', default=1,
                      help='Vertical rotation in degrees between pictures', metavar='INT')
    parser.add_option('-d', '--delay', type='int', dest='delay', default=0,
                      help='Delay between rotation and picture taking', metavar='INT')
    parser.add_option('-b', '--batch', type='int', dest='batch', default=1,
                      help='Batch download after taking all pictures', metavar='INT')
    parser.add_option('-g', '--gphoto2', type='string', dest='gphoto2', default='/main/settings/capturetarget=1,/main/imgsettings/imagequality=0,/main/imgsettings/imagesize=2',
                      help='Comma separated configurations for gphoto2', metavar='CONFIGS')
    
    (opt, args) = parser.parse_args()

    # read config file for logging options
    try:
        logging.config.fileConfig(opt.config_file)
        logging.logProcesses = 0

        # read config file for other options
        config = ConfigParser.SafeConfigParser()
        config.optionxform = str # case sensitive
        config.read(opt.config_file)
    except ConfigParser.NoSectionError, e:
        print e.__str__()
    
    try:
        camZilla = CamZillaPluginClass(MainDummy(), dict(config.items('CamZillaPlugin_options')))
        camZilla.start()
        camZilla.action('start(%d,%d) pictures(%d,%d) rotation(%d,%d) delay(%d) batch(%d) gphoto2(%s)' % (opt.startX, opt.startY, opt.picturesX, opt.picturesY, opt.rotationX, opt.rotationY, opt.delay, opt.batch, opt.gphoto2))
        signal.pause()
    except KeyboardInterrupt:
        print 'KeyboardInterrupt'
        camZilla.stop()
        