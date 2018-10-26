import os
import numpy as np
import cv2
import ProcessFunction as Func

if __name__ == '__main__':
    ground_height = 0
    pixel_size = 0.00157424E-3  # unit: m/px (mm/px * 10 ^ -3)

    for root, dirs, files in os.walk('./Data'):
        for file in files:
            filename = os.path.splitext(file)[0]
            extension = os.path.splitext(file)[1]
            file_path = root + '/' + file

            if extension == '.JPG':
                print('Read the image - ' + file)
                image = cv2.imread(file_path)

                # 0. Extract Interior orientation parameters from the image
                focal_length = Func.getFocalLength(file_path) # unit: m

                # 1. Restore the image based on orientation information
                restored_image = Func.restoreOrientation(image, file_path)
                image_rows = restored_image.shape[0]
                image_cols = restored_image.shape[1]

            else:
                print('Read EOP - ' + file)
                print('Latitude | Longitude | Height | Omega | Phi | Kappa')
                eo = Func.readEO(file_path)
                eo = Func.convertCoordinateSystem(eo)

                # 2. Extract a projected boundary of the image
                bbox = Func.boundary(restored_image, eo, ground_height, pixel_size, focal_length)

                gsd = (pixel_size * (eo[2] - ground_height)) / focal_length  # unit: m/px
                projected_rows = (bbox[1] - bbox[0]) / gsd
                projected_cols = (bbox[3] - bbox[2]) / gsd

                coord1 = np.zeros(shape=(3, 1))

                for row in range(int(projected_rows)):
                    for col in range(int(projected_cols)):
                        coord1[0] = bbox[0] + col * gsd
                        coord1[1] = bbox[3] - row * gsd
                        coord1[2] = ground_height

                        # 3. Backprojection
                        coord2 = Func.backProjection(coord1, eo, [image_rows, image_cols], pixel_size, focal_length)

                        # 4. Resampling
                        pixel = Func.resample(coord2, restored_image)
                        bbox[row, col] = pixel

                #cv2.imwrite(root + '/' + file, bbox)