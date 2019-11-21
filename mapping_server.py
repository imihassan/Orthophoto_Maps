import socket
import os
import cv2
import time
import numpy as np
from struct import *
import pandas as pd
import json
from ortho_func.system_calibration import calibrate
from ortho_func.Orthophoto import rectify
from ortho_func.EoData import convertCoordinateSystem, Rot3D
from ortho_func.Boundary import pcs2ccs, projection
from copy import copy

# For test
R_CB = np.array(
[[0.990635238726878, 0.135295782209043, 0.0183541578119133],
 [-0.135993334134149, 0.989711806459606, 0.0444561944563446],
 [-0.0121505910810649, -0.0465359159242159, 0.998842716179817]], dtype=float)

data_store = 'C:/innomap_real/dataStore/'     # Have to be defined already
bbox_total = []

#########################
# Client for map viewer #
#########################
s1 = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
s1.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
dest = ("localhost", 57820)
print("binding...")


def load_log(file_path):
    df = pd.read_csv(file_path, low_memory=False)
    df = df[df['CAMERA_INFO.recordState'] == 'Starting']
    df = df[['OSD.longitude', 'OSD.latitude', 'OSD.height [m]',
             'GIMBAL.roll', 'GIMBAL.pitch', 'GIMBAL.yaw']]

    global log_eo
    log_eo = df.to_numpy()


def load_io(file_path):
    # model = cv2.VideoCapture(filePath + '.MOV')
    model = 'FC6310R'

    # model_name, sensor_width(mm), focal_length(mm)
    io_list = np.array([['FC6310R', 13.2, 8.8],  # Phantom4RTK
                        ['FC220', 6.3, 4.3],  # Mavic
                        ['FC6520', 17.3, 15]]  # Inspire2
                       )

    sensor_width_mm = float(io_list[io_list[:, 0] == model][0, 1])
    focal_length_mm = float(io_list[io_list[:, 0] == model][0, 2])

    global io
    io = [sensor_width_mm, focal_length_mm]


def create_bbox_json(frame_number, object_id, object_type, boundary):
    """
    Create json of boundary box
    :param object_id:
    :param object_type:
    :param boundary:
    :return: list of information of boundary box ... json array
    """
    bbox_info = {
        "frame_number": frame_number,
        "objects_id": object_id,     # uuid
        "boundary": "POLYGON ((%f %f, %f %f, %f %f, %f %f, %f %f))"
                    % (boundary[0, 0], boundary[1, 0],
                       boundary[0, 1], boundary[1, 1],
                       boundary[0, 2], boundary[1, 2],
                       boundary[0, 3], boundary[1, 3],
                       boundary[0, 0], boundary[1, 0]),
        "objects_type": object_type
    }

    return bbox_info


def read_memmap(rows, cols, ch):
    print("memmap read")
    time.sleep(1)
    np_image = np.memmap('frame_image', mode='r', shape=(rows, cols, ch), dtype=np.uint8)
    print('shape :', np_image.shape, 'type:', np_image.dtype)
    # cv2.imshow('Test', np_image)
    # cv2.waitKey(0)
    return np_image


def PATH(path, video_id):
    file_path_wo_ext = path[:-4]
    # project_path = file_path_wo_ext.split('/')[-1] + '/'
    global uuid
    uuid = video_id
    if not(os.path.isdir(data_store + uuid)):
        os.mkdir(data_store + uuid)

    load_log(path)  # Extract EO
    load_io(path)   # Extract IO


def FRAM(np_image, frame_number):
    ################################
    # Sync log w.r.t. frame_number #
    ################################
    eo = log_eo[int((frame_number - 1) / 3 + 1), :]

    tm_eo = convertCoordinateSystem(eo, epsg=3857)
    # System calibration using gimbal angle
    # eo[3] = eo[3] * np.pi / 180
    # eo[4] = (eo[4] + 90) * np.pi / 180
    # eo[5] = -eo[5] * np.pi / 180

    eo[3:] = eo[3:] * np.pi / 180
    OPK = calibrate(eo[3], eo[4], eo[5], R_CB)
    eo[3:] = OPK
    print('Easting | Northing | Height | Omega | Phi | Kappa')
    print(eo)

    ###########################
    # Rectify the given image #
    ###########################
    path_orthophoto, bbox_wkt = rectify(data_store, uuid+'/', img=np_image,
                                        rectified_fname='Rectified_' + str(frame_number), eo=tm_eo,
                                        ground_height=0, sensor_width=io[0], focal_length=io[1])

    ortho_json = {
        "uid": uuid,  # String
        "path": path_orthophoto,  # String
        "frame_number": frame_number,  # Number
        "position": [tm_eo[0], tm_eo[1]],  # Array
        "bbox": bbox_wkt,  # WKT ... String
    }

    bbox_to_add = []
    count = 0
    for i in range(len(bbox_total)):
        if bbox_total[i]["frame_number"] == ortho_json["frame_number"]:
            bbox_to_add.append(bbox_total[i])
            count = count + 1

    del bbox_total[:(count - 1)]

    ortho_json["objects"] = bbox_to_add
    print(ortho_json)
    # https://stackoverflow.com/questions/4547274/convert-a-python-dict-to-a-string-and-back
    str_objects_info = json.dumps(ortho_json)

    #############################################
    # Send object information to web map viewer #
    #############################################
    fmt = '<4si' + str(len(str_objects_info)) + 's'  # s: string, i: int
    data_to_send = pack(fmt, b"MAPP", len(str_objects_info), str_objects_info.encode())
    s1.sendto(data_to_send, dest)


def INFE(infe_res, cols, rows):
    # infe_res = [
    #     {
    #         "frame_number": 1,
    #         "objects_id": "85f46f4c-99d9-40da-880e-b943621f32c0",
    #         "boundary": [[1469,129],[1469,230],[1570,230],[1570,129]],
    #         "objects_type": 0
    #     },
    #     {
    #         "frame_number": 1,
    #         "objects_id": "85f46f4c-99d9-40da-880e-b943621f32c1",
    #         "boundary": [[469,129],[469,230],[570,230],[570,129]],
    #         "objects_type": 0
    #     }
    # ]

    frame_number = infe_res[0]["frame_number"]

    eo = log_eo[int((frame_number - 1) / 3 + 1), :]
    tm_eo = convertCoordinateSystem(eo, epsg=3857)
    # System calibration using gimbal angle
    # eo[3] = eo[3] * np.pi / 180
    # eo[4] = (eo[4] + 90) * np.pi / 180
    # eo[5] = -eo[5] * np.pi / 180

    eo[3:] = eo[3:] * np.pi / 180
    OPK = calibrate(eo[3], eo[4], eo[5], R_CB)
    eo[3:] = OPK

    R_GC = Rot3D(tm_eo)
    R_CG = R_GC.transpose()
    print('Easting | Northing | Height | Omega | Phi | Kappa')
    print(eo)

    for i in range(len(infe_res)):
        object_id = infe_res[i]["objects_id"]
        object_type = infe_res[i]["objects_type"]
        bbox = infe_res[i]["boundary"]
        bbox_px = np.array(bbox).transpose()

        # Convert pixel coordinate system to camera coordinate system
        # input params unit: px, px, px, mm/px, mm
        pixel_size = io[0] / cols
        bbox_camera = pcs2ccs(bbox_px, rows, cols, pixel_size, io[1])  # shape: 3(x, y, z) x points

        # Project camera coordinates to ground coordinates
        # input params unit: mm, _, _, m
        bbox_world = projection(bbox_camera, tm_eo, R_CG, 0)  # shape: 2(x, y) x points | np.array

        # Create boundary box in type of json for each inference data
        bbox_info = create_bbox_json(frame_number, object_id, object_type, bbox_world)  # dictionary
        bbox_total.append(bbox_info)
    print(bbox_total)


def SEND(bbox_total, ortho_json):
    #########################
    # Client for map viewer #
    #########################
    s1 = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s1.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    dest = ("localhost", 57820)
    print("binding...")

    bbox_tmp = copy(bbox_total)

    bbox_to_add = []
    iter = len(bbox_total)

    count = 0
    for i in range(iter):
        if bbox_total[i]["frame_number"] == ortho_json["frame_number"]:
            bbox_to_add.append(bbox_total)
            count = count + 1

    del bbox_total[:count-1]

    ortho_json["objects"] = bbox_to_add
    print(ortho_json)
    # https://stackoverflow.com/questions/4547274/convert-a-python-dict-to-a-string-and-back
    str_objects_info = json.dumps(ortho_json)

    #############################################
    # Send object information to web map viewer #
    #############################################
    fmt = '<4si' + str(len(str_objects_info)) + 's'     # s: string, i: int
    data_to_send = pack(fmt, b"MAPP", len(str_objects_info), str_objects_info.encode())
    s1.sendto(data_to_send, dest)


if __name__ == '__main__':
    PATH(path="C:/DJI_0018.csv", video_id="525c671317165f77b0d31543634093abb")
    # PATH(path="C:/DJI_0030.csv", video_id="525c671317165f77b0d31543634093aba")

    infe_res = [
        {
            "frame_number": 181,
            "objects_id": "85f46f4c-99d9-40da-880e-b943621f32c0",
            "boundary": [[1469, 129], [1469, 230], [1670, 230], [1670, 129]],
            "objects_type": 0
        },
        {
            "frame_number": 181,
            "objects_id": "85f46f4c-99d9-40da-880e-b943621f32c1",
            "boundary": [[469, 129], [469, 230], [570, 230], [570, 129]],
            "objects_type": 0
        }
    ]

    # video_path = 'C:/DJI_0114.MOV'
    video_path = 'C:/DJI_0018.MOV'
    # video_path = 'C:/DJI_0030.MOV'
    vidcap = cv2.VideoCapture(video_path)

    count = 0
    while (vidcap.isOpened()):
        ret, np_image = vidcap.read()
        rows = int(vidcap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        cols = int(vidcap.get(cv2.CAP_PROP_FRAME_WIDTH))

        if (int(vidcap.get(1)) % 90 == 1):
            frame_number = int(vidcap.get(cv2.CAP_PROP_POS_FRAMES))
            # mm = np.memmap('frame_image', mode='w+', shape=np_image.shape, dtype=np_image.dtype)
            # mm[:] = np_image[:]
            # mm.flush()
            # del mm
            print(np_image.shape)

            INFE(infe_res, cols, rows)

            # frame_number = 1
            FRAM(np_image, frame_number)

    print("Hello")