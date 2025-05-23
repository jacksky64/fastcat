# !/usr/bin/env python 
# -*- coding: UTF-8 -*-

"""
Fastcat a rapid and accurate CBCT simulator.

Contains code from xpecgen.py to simulate spectrum:
A module to calculate x-ray spectrum generated in tungsten anodes.
"""

from __future__ import print_function

import os
from glob import glob

import numpy as np
from numpy import cos

try:
    from matplotlib.colors import LogNorm
    PLOT_AVAILABLE = True
except ImportError:
    PLOT_AVAILABLE = False

from scipy.signal import fftconvolve
from scipy.ndimage import gaussian_filter
from scipy.stats import norm
from scipy.optimize import curve_fit

data_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")


class Detector:
    """
    Detector class that holds the optical properties of a detector

    """

    def __init__(self, spectrum, detector,specify_file=False,file=None):
        """
        The spectrum is used to calculate the MTF for the detector

        Parameters
        ----------

        spectrum: Fastcat Spectrum Object
            An energy spectrum of a beam for which the MTF is
            calculated.
        detector: String
            The name of the detector. One of the detector folders
            in data/Detectors. ex. 'CSI-784-micrometer' numbers are
            the pixel pitch

        Returns
        -------
        Fastcat Detector object
        """
        self.name = detector

        if hasattr(spectrum,'get_points'):
            spectrum.x, spectrum.y = spectrum.get_points() #! This might throw errors!
        else:
            spectrum.x, spectrum.y = spectrum.get_spectrum() #! This might throw errors!

        dump_files = os.path.join(
            data_path, "Detectors", detector, "*phsp.npy"
        )
        if specify_file:
            self.deposition_efficiency_file = file
        else:
            self.deposition_efficiency_file = os.path.join(
                data_path, "Detectors", detector, "EnergyDeposition.npy"
            )

        files = sorted(glob(dump_files))

        for ii, file in enumerate(files):

            if ii == 0:

                # Make the first entry zeros
                first_kernel = np.load(file).squeeze()
                kernels = np.zeros(
                    [
                        len(files) + 1,
                        first_kernel.shape[0],
                        first_kernel.shape[1],
                    ]
                )

            kernels[ii + 1] = np.load(file).squeeze()

        fluence = spectrum.y / np.sum(spectrum.y)

        deposition_summed = np.load(
            self.deposition_efficiency_file, allow_pickle=True
        )
        deposition_summed = np.insert(deposition_summed[0], 0, 0)

#         if len(deposition_summed) == 16:
#             deposition_summed = np.insert(deposition_summed, 0, 0)
        
        if len(deposition_summed) == 19:
            original_energies_keV = np.array(
                [
                    0,
                    10,
                    20,
                    30,
                    40,
                    50,
                    60,
                    70,
                    80,
                    90,
                    100,
                    300,
                    500,
                    700,
                    900,
                    1000,
                    2000,
                    4000,
                    6000,
                ]
            )
        else:
            original_energies_keV = np.array(
                [
                    0,
                    30,
                    40,
                    50,
                    60,
                    70,
                    80,
                    90,
                    100,
                    300,
                    500,
                    700,
                    900,
                    1000,
                    2000,
                    4000,
                    6000,
                ]
            )
        
#         print(len(deposition_summed),len(original_energies_keV),kernels.shape)
        # Divide by the energy to get the photon count
        # plus a factor 355000 for the original number of photons
        
        deposition_summed[1:] /= (
            original_energies_keV[1:] / 355
        )  # I took this out and put it back in again
        deposition_interpolated = np.interp(
            spectrum.x, original_energies_keV, deposition_summed
        )
        super_kernel = np.zeros(
            [len(fluence), kernels.shape[1], kernels.shape[2]]
        )

        for ii in range(kernels.shape[1]):
            for jj in range(kernels.shape[2]):

                super_kernel[:, ii, jj] = np.interp(
                    np.array(spectrum.x),
                    original_energies_keV,
                    kernels[:, ii, jj],
                )

        # import ipdb;ipdb.set_trace()
        weights = fluence * deposition_interpolated
        self.weights = weights / np.sum(weights)
        self.fluence = fluence
        self.deposition_interpolated = deposition_interpolated

        self.kernels = kernels
        self.kernel = super_kernel.T @ self.weights
        self.kernel_show = self.kernel.copy()
        self.pitch = int(detector[-14:-11]) / 1000  # mm

    def get_plot(self, place, show_mesh=True, prepare_format=True):
        """
        Prepare a plot of the data in the given place

        Args:
            place:
            The class whose method plot is called to
            produce the plot (e.g., matplotlib.pyplot).
            show_mesh (bool):
            Whether to plot the points over the continuous line as circles.
            prepare_format (bool):
            Whether to include ticks and labels in the plot.
            peak_shape:
            The window function used to plot the peaks.
            See :obj:`triangle` for an example.

        """
        if prepare_format:
            place.tick_params(axis="both", which="major", labelsize=10)
            place.tick_params(axis="both", which="minor", labelsize=8)

        im = place.imshow(self.kernel_show, cmap='jet', norm=LogNorm())
        # place.colorbar()
        place.set_title("Optical Spread Function")
        place.set_xlabel("X [pix]")
        place.set_ylabel("Y [pix]")
        return im

    #         place.colorbar()
    
    def calc_mtf(
        self, h=4096, w=2048, step=32, angle=2.3, lsf_width=0.3, nbins=818,gauss_fit=False
    ):

        """
        Prepare a plot of the data in the given place of the MTF
        Also performs the MTF calulation

        Args:
            place:
            The class whose method plot is called to
            produce the plot (e.g., matplotlib.pyplot).
            peak_shape: The window function used to plot the peaks.
            See :obj:`triangle` for an example.

        """

        # --- Make a high res line ---

        high_res = np.zeros([h, w])
        Y, X = np.mgrid[:h, :w]
        dist_from_line = np.abs(
            (X - high_res.shape[1] / 2) + Y * np.tan(angle * np.pi / 180)
        )
        # The MTF is from a 0.3 mm pixel times
        # the angle times 16 since it will be averaged over 32 pix
        num_pix = lsf_width * 1 / cos(angle * np.pi / 180) / self.pitch * 16
        high_res[dist_from_line < num_pix] = 1
        # --- Average to make low res line ---
        # Ugly sorry
        low_res = np.array(
            [
                [
                    np.mean(high_res[ii : ii + step, jj : jj + step])
                    for ii in range(0, h, step)
                ]
                for jj in range(0, w, step)
            ]
        ).T

        # --- Convlolve with the kernel ---
        lsf_image = fftconvolve(
            low_res, self.kernel_show / np.sum(self.kernel_show), mode="same"
        )

        # --- Pad and presample ---
        pad_len = int((512 - lsf_image.shape[1]) / 2)
        lsf_image = np.pad(
            lsf_image, ((0, 0), (pad_len, pad_len)), mode="constant"
        )
        Y, X = np.mgrid[: lsf_image.shape[0], : lsf_image.shape[1]]
        center = int(lsf_image.shape[1] / 2)
        # pitch needs to convert to cm from mm
        dist_from_line = (
            (X + Y * np.tan(angle * np.pi / 180) - center + 0.5) * self.pitch / 10
        )

        # --- Crop the convolved edges ---
        inds = np.argsort(dist_from_line[10:-10, :].flatten())
        line = dist_from_line[10:-10, :].flatten()[inds]
        lsf = lsf_image[10:-10, :].flatten()[inds]
        self.lsf = lsf
        self.line = line
        self.n, self.bins = np.histogram(line, nbins, weights=lsf, density=True)
        
        if gauss_fit:
            x = self.bins[1:]
            y = self.n

            # weighted arithmetic mean (corrected - check the section below)
            mean = sum(x * y) / sum(y)
            sigma = np.sqrt(sum(y * (x - mean)**2) / sum(y))

            def Gauss(x, a, x0, sigma):
                    return a * np.exp(-(x - x0)**2 / (2 * sigma**2))
            
            self.bins = np.linspace(-1.5,1.5,1000)
            popt,pcov = curve_fit(Gauss, x, y, p0=[max(y), mean, sigma])

            self.n = Gauss(self.bins, *popt) 

        # mean, std = norm.fit(line)
        mtf = np.absolute(np.fft.fft(self.n))
        mtf_final = np.fft.fftshift(mtf)
        N = len(mtf)
        T = np.mean(np.diff(self.bins))
        xf = np.linspace(0.0, 1.0 / (2.0 * T), int((N - 1) / 2))
        mm = np.argmax(mtf_final)

        self.mtf = mtf_final[mm + 1 :] / mtf_final[mm + 1]
        self.freq = xf / 10

    def get_plot_mtf_real(
        self, place, label=""
    ):

        """
        Prepare a plot of the data in the given place of the MTF
        Also performs the MTF calulation

        Args:
            place:
            The class whose method plot is called to
            produce the plot (e.g., matplotlib.pyplot).
            peak_shape: The window function used to plot the peaks.
            See :obj:`triangle` for an example.

        """

        self.calc_mtf()

        if place is not None:
            place.plot(
                self.freq,
                self.mtf,
                "--",
                linewidth=1.1,
                markersize=2,
                label=label,
            )
            place.set_xlim((0, 1 / (2 * self.pitch)))
            place.set_xlabel("Spatial Frequency [1/mm]")
            place.set_ylabel("MTF")
            place.legend()
            place.grid(True)

    def add_focal_spot(self, fs_size_in_mm):
        """
        The most basic focal spot one can think of.
        Do better, do better, got it.

        Parameters
        ----------
        fs_size_in_mm: float
            The focal spot size

        """
        self.fs_size = fs_size_in_mm / self.pitch

        if self.kernel.shape[0] < 30:
            # print(self.kernel.shape[0])
            self.kernel_show = gaussian_filter(
                np.pad(self.kernel, ((15, 15), (15, 15))), sigma=self.fs_size
            )
        else:
            self.kernel_show = gaussian_filter(self.kernel, sigma=self.fs_size)

    def __str__(self):
        str_det = f'''
Fastcat Detector Object
------------------------

    Detector:    {self.name}
    Pitch:       {self.pitch}
    Focal spot:  {self.fs_size if hasattr(self,'fs_size') else None}

    Parameter files at:
    {self.deposition_efficiency_file[:-20]}
        '''
        return str_det
