import sys
import warnings

import numpy as np
import numbers
import math
from collections import defaultdict
import types
from scipy.interpolate import splprep, splev
import matplotlib.pyplot as plt
import matplotlib as mpl

import astropy.units as u
import astropy.constants as c
from astropy.modeling import models, fitting, polynomial
from astropy.stats import sigma_clip
from astropy.io import fits
import shapely.geometry as geometry
from shapely.geometry import LineString
import matplotlib.colors as colors

from radfil import profile_tools
from plummer import Plummer1D
from matplotlib.patches import Rectangle

import styles

class radfil(object):

    """
    Container object which stores the required metadata for building the radial profiles

    Parameters
    ------
    image : numpy.ndarray
        A 2D array of the data to be analyzed.

    mask: numpy.ndarray 
        A 2D array defining the shape of the filament; must be of boolean
        type and the same shape as the image array.
        A mask is optional ONLY if filspine is provided

    beamwidth: float 
        A float in units of arcseconds indicating the beamwidth of the image array.

    header : astropy.io.fits.Header
        The header corresponding to the image array

    distance : a number-like object 
        Distance to the filament; must be entered in pc

    filspine: numpy.ndarray 
        A 2D array defining the longest path through the filament mask; must
        be of boolean type and the same shape as the image array. Can also create
        your own with the FilFinder package using the "make_fil_spine" method below.
        A filspine is optional when mask is provided. 

    imgscale: float 
        In cases where the header is not in the standrad format, imgscale is
        specified.  This is overwritten when the header and proper header keys
        exist.

    Attributes
    ----------
        imgscale : float
           The image scale in pc of each pixel
    """

    def __init__(self, image, mask=None, header = None, distance = None, filspine = None, imgscale = None):

        # Read image
        if (isinstance(image, np.ndarray)) and (image.ndim == 2):
            self.image = image
        else:
            raise TypeError("The input `image` has to be a 2D numpy array.")

        # Read mask if user entered it...
        if mask is not None:
            if (isinstance(mask, np.ndarray)) and (mask.ndim == 2) and (mask.dtype=='bool'):
                self.mask = (mask & np.isfinite(self.image))
            else:
                raise TypeError("The input `mask` has to be a 2d numpy array of boolean type.")

        #If user did not enter mask, make sure they entered filspine correctly
        if mask is None is True & ((isinstance(filspine, np.ndarray)) and (filspine.ndim == 2) and (filspine.dtype=='bool')) is False:
            raise TypeError("If mask is None, you must enter a filspine argument as a 2D array the same shape as image")
        else:
            self.mask=mask

        # Read header
        if (isinstance(header, fits.header.Header)):
            self.header = header
            if ("CDELT1" in self.header.keys()) and (abs(self.header["CDELT1"]) == abs(self.header["CDELT2"])):
                self.imgscale_ang = abs(header["CDELT1"])*u.deg # degrees
            elif ("CD1_1" in self.header.keys()) and (abs(self.header["CD1_1"]) == abs(self.header["CD2_2"])):
                self.imgscale_ang = abs(header["CD1_1"])*u.deg # degrees
        else:
            self.header = None
            self.distance = None
            self.imgscale_ang = None
            warnings.warn("`header` and `distance` will not be used; all calculations in pixel units.")

        # Read distance
        ## `self.distance` is in pc.
        if isinstance(distance, numbers.Number):
            self.distance = float(distance) * u.pc
        ## if distance is wrong or None, calculate in pixel units.
        else:
            self.distance = None
            self.header = None
            warnings.warn("`header` and `distance` will not be used; all calculations in pixel units.")


        #if user enters a filspine argument (i.e. filspine!=None), make sure it's a 2D boolean array.
        # if it's not, raise an error
        if filspine is not None:

            if (isinstance(filspine, np.ndarray) and (filspine.ndim == 2)) and (filspine.dtype=='bool'):
                self.filspine=filspine

                # calculate "imgscale" when the spine is provided. This saves users
                # the trouble to run `make_fil_spine`.
                if (isinstance(filspine, np.ndarray) and (filspine.ndim == 2)):
                    # Calculate pixel scale ("imgscale"), in the unit of pc/Deal with non-standard fits header
                    if (self.header is not None):
                        if ("CDELT1" in self.header.keys()) and (abs(self.header["CDELT1"]) == abs(self.header["CDELT2"])):
                            # `imgscale` in u.pc
                            ## The change to u.pc has not been cleaned up for the rest of the code, yet.
                            self.imgscale = abs(header["CDELT1"]) * (np.pi / 180.0) * self.distance
                        elif ("CD1_1" in self.header.keys()) and (abs(self.header["CD1_1"]) == abs(self.header["CD2_2"])):
                            # `imgscale` in u.pc
                            self.imgscale = abs(header["CD1_1"]) * (np.pi / 180.0) * self.distance
                        else:
                            if isinstance(imgscale, numbers.Number):
                                self.imgscale = float(imgscale) * u.pc
                                warnings.warn("The keyword `imgscale`, instead of the header, is used in calculations of physical distances.")
                            else:
                                self.imgscale = 1. * u.pix
                                warnings.warn("Calculate in pixel scales.")
                    ##
                    else:
                        self.imgscale = 1. * u.pix
                        warnings.warn("Calculate in pixel scales.")
            else:
                raise TypeError("If you input a filspine argument it must be a 2D array of boolean type")
        else:
            self.filspine = None
            self.imgscale = None

        # Return a dictionary to store the key setup Parameters
        params = {'image': self.image,
                  'mask': self.mask,
                  'header': self.header,
                  'distance': self.distance,
                  'imgscale': self.imgscale}
        self._params = {'__init__': params}

        # Return a dictionary to store the results.
        self._results = {'make_fil_spine': {'filspine': self.filspine}}


    def make_fil_spine(self,beamwidth = None,verbose = False):

        """
        Create filament spine using the FilFinder package 'longest path' option

        Parameters:
         ----------

        verbose: boolean
            A boolean indicating whether you want to enable FilFinder plotting of filament spine

        Attributes
        ----------
        filspine : numpy.ndarray
           A 2D boolean array defining the longest path through the filament mask
           
        length: float
            The length of the filament; only accessible if make_fil_spine is called
        """

        try:
            from fil_finder import fil_finder_2D

        except ImportError:
            raise ImportError("You must install the fil_finder package to continue")

        # Read beamwidth
        if isinstance(beamwidth, numbers.Number):
            if (self.header is not None):
                self.beamwidth = beamwidth * u.arcsec
            else:
                self.beamwidth = beamwidth * u.pix
        else:
            self.beamwidth = None
            raise TypeError("A beamwidth is required")


        # fil_finder
        ## Let fil_fineder deal with the beamwidth
        if (self.header is not None):
            fils = fil_finder_2D(self.image,
                                 header = self.header,
                                 beamwidth = self.beamwidth,
                                 distance = self.distance,
                                 mask = self.mask)
        ## scale-free
        else:
            fils = fil_finder_2D(self.image,
                                 beamwidth = self.beamwidth,
                                 skel_thresh = 15,
                                 mask = self.mask)
            ## 15 is chosen to be roughly 0.3 pc at the distance to Per B5 (260 pc).
            ## Consider allowing users to input in the future.

        # do the skeletonization
        fils.medskel(verbose=verbose)

        # Find shortest path through skeleton
        analysis = fils.analyze_skeletons(verbose=verbose)

        # Return the reults.
        self.filspine = fils.skeleton_longpath.astype(bool)
        if (self.header is not None):
            self.length = np.sum(analysis.lengths) * u.pc
            self.imgscale = fils.imgscale * u.pc
        else:
            self.length = np.sum(analysis.lengths) * u.pix
            self.imgscale = fils.imgscale * u.pix

        # Return a dictionary to store the key setup Parameters
        self._params['__init__']['imgscale'] = self.imgscale
        params = {'beamwidth': self.beamwidth}
        self._params['make_fil_spine'] = params

        # Return a dictionary to store the results
        self._results['make_fil_spine']['filspine'] = self.filspine
        self._results['make_fil_spine']['length'] = self.length

        return self

    def build_profile(self, pts_mask = None, samp_int=3, bins = None, shift = True, wrap = False, cut = True, cutdist=None):
        """
        Build the filament profile using the inputted or recently created filament spine

        Parameters
        ----------
        self: An instance of the radfil_class

        pts_mask: numpy.ndarray
            A 2D array masking out any regions from image array you don't want to sample; must be of boolean
            type and the same shape as the image array. The spine points within the masked out region will then be
            excluded from the list of cuts and the master profile. 

        samp_int: integer (default=3)
            An integer indicating how frequently you'd like to make sample cuts
            across the filament. Very roughly corresponds to sampling frequency in pixels

        bins: int or 1D numpy.ndarray, optional
            The number of bins (int) or the actual bin edges (numpy array) you'd like to divide the profile into. 
            If entered as an integer "n", the profile will be divided into n bins, from the minimum radial distance
            found in any cut to the maximum radial distance found in any cut. If an array (i.e. np.linspace(-2,2,100)). 
            the array values will represent the bin edges (i.e. 100 bins evenly distributed between -2 and 2).
            If entered, the profile will be averaged in each bin, and the fit_profile method will only consider the bin-averaged data

        shift: boolean (default = True)
            Indicates whether to shift the profile to center at the peak value. The peak value is determined
            by searching for the peak value along each cut, either confined within the filament mask,
            or confined within some value cutdist from the spine (if no mask is entered)

        wrap: boolean (default = False)
            Indicates whether to wrap around the central pixel, so that the final profile
            will be a "half profile" with the peak near/at the center (depending on
            whether it's shifted).

        make_cut: boolean (default = True)
            Indicates whether to perform cuts when extracting the profile. Since
            the original spine found by `fil_finder_2D` is not likely differentiable
            everywhere, setting `cut = True` necessitates a spline fit to smoothe
            the spine. Setting `cut = False` will make `radfil` calculate a distance and a
            height/value for every pixel inside the mask.

        cutdist: float or int
            If using a pre-computed spine, and you would like to shift to the peak column density value (shift=True),
            you must enter a cutdist, which indicates the radial distance from the spine you'd like to search for the
            peak column density along each cut. This will create a mask whose outer boundary is
            defined by all points equidistant from the spine at the value of cutdist.


        Attributes
        ----------

        xall, yall: 1D numpy.ndarray (list-like)
            All data points (with or without cutting).

        xbeforespline, ybeforespline: 1D numpy.ndarray (list-like)
            Positions of the "filament" identified by `fil_finder_2D`, in pixel
            units.  This is before smoothing done with `spline`.

        xspline, yspline: 1D numpy.ndarray (list-like)
            Positions of the spline points used for cuts, in pixel units.

        masterx, mastery: 1D numpy.ndarray (list-like)
            The profile (radial distances and height/column density/intensity)
            obtained by `profile_builder`.

        dictionary_cuts: Python dictionary
            A dictionary containing the profile (radian distances and height)
            for each cut along the spline, as two lists--one for the distance,
            and the other for the height.
        """


        # Read shift, wrap, cut, and samp_int
        ## shift
        if isinstance(shift, bool):
            self.shift = shift
        else:
            raise TypeError("shift has to be a boolean value. See documentation.")
        ## wrap
        if isinstance(wrap, bool):
            self.wrap = wrap
        else:
            raise TypeError("wrap has to be a boolean value. See documentation.")
        ## cut
        if isinstance(cut, bool):
            self.cutting = cut
        else:
            raise TypeError("cut has to be a boolean value. See documentation.")
        ## samp_int
        if isinstance(samp_int, int):
            self.samp_int = samp_int
        else:
            self.samp_int = None
            warnings.warn("samp_int has to be an integer; ignored for now. See documentation.")

        # Read the pts_mask
        if isinstance(pts_mask, np.ndarray) and (pts_mask.ndim == 2):
            self.pts_mask = pts_mask.astype(bool)
        else:
            self.pts_mask = None

        #extract x and y coordinates of filament spine
        pixcrd = np.where(self.filspine)

        # Sort these points by distance along the spine
        x, y = profile_tools.curveorder(pixcrd[1], pixcrd[0])
        self.xbeforespline, self.ybeforespline = x, y

        # If cut
        if self.cutting:
            # Filter out wrong samp_int
            if self.samp_int is None:
                raise TypeError("samp_int has to be an integer, when cut is True.")
            # Spline calculation:
            ##set the spline parameters
            k = 3
            nest = -1 # estimate of number of knots needed (-1 = maximal)
            ## find the knot points
            tckp, up, = splprep([x,y], k = k, nest = -1)
            ## evaluate spline
            xspline, yspline = splev(up, tckp)
            xprime, yprime = splev(up, tckp, der=1)
            ## Notice that the result containt points on the spline that are not
            ## evenly sampled.  This might introduce biases when using a single
            ## number `samp_int`.

            #Make sure no-mask case works. If they want to shift and have no mask, need to enter cutdist; otherwise raise warning
            #If everything checks out, create the new mask for them using their inputted cutdist
            if shift is True and self.mask is None:
                if isinstance(cutdist, numbers.Number):
                    try:
                        from descartes import PolygonPatch

                    except ImportError:
                        raise ImportError("You must install the descartes package to continue")

                    self.cutdist = float(cutdist) * self.imgscale.unit

                    spine=LineString([(i[0], i[1]) for i in zip(xspline,yspline)])

                    boundary = spine.buffer(self.cutdist.value/self.imgscale.value)
                    boundarypatch=PolygonPatch(boundary)

                    boundaryline=boundarypatch.get_verts() #green boundary of MST filament

                    # calculate the x and y points possibly within the image
                    y_int = np.arange(0, self.image.shape[0])
                    x_int = np.arange(0, self.image.shape[1])

                    # create a list of possible coordinates
                    g = np.meshgrid(x_int, y_int)
                    coords = list(zip(*(c.flat for c in g)))

                    # create the list of valid coordinates inside contours
                    newmaskpoints = np.vstack([p for p in coords if boundarypatch.contains_point(p, radius=0)])

                    self.mask=np.zeros(self.image.shape)
                    self.mask[newmaskpoints[:,1],newmaskpoints[:,0]]=1
                    self.mask=self.mask.astype(bool)

                else:
                    raise TypeError("If shift=True and no mask is provided, you need to enter a valid cutdist in pc, which indicates \
                                the radial distance from the spine along which to search for the peak column density pixel")


            ## Plot the results ##########
            ## prepare
            vmin, vmax = np.min(self.image[self.mask]), np.nanpercentile(self.image[self.mask], 98.)
            xmin, xmax = np.where(self.mask)[1].min(), np.where(self.mask)[1].max()
            ymin, ymax = np.where(self.mask)[0].min(), np.where(self.mask)[0].max()
            ## plot
            fig=plt.figure(figsize=(10,5))
            ax=plt.gca()
            ax.imshow(self.image,
                      origin='lower',
                      cmap='gray',
                      interpolation='none',
                      norm = colors.LogNorm(vmin = vmin, vmax =  vmax))
            ax.contourf(self.mask,
                        levels = [0., .5],
                        colors = 'w')
            ax.plot(xspline, yspline, 'r', label='fit', lw=3, alpha=1.0)
            ax.set_xlim(max(0., xmin-.1*(xmax-xmin)), min(self.mask.shape[1]-.5, xmax+.1*(xmax-xmin)))
            ax.set_ylim(max(0., ymin-.1*(ymax-ymin)), min(self.mask.shape[0]-.5, ymax+.1*(ymax-ymin)))
            ax.set_xticklabels([])
            ax.set_yticklabels([])

            self.fig, self.ax = fig, ax

            # Only points within pts_mask AND the original mask are used.
            if (self.pts_mask is not None):
                pts_mask = ((self.pts_mask[np.round(yspline[1:-1:self.samp_int]).astype(int),
                                           np.round(xspline[1:-1:self.samp_int]).astype(int)]) &\
                            (self.mask[np.round(yspline[1:-1:self.samp_int]).astype(int),
                                       np.round(xspline[1:-1:self.samp_int]).astype(int)]))
            else:
                pts_mask = (self.mask[np.round(yspline[1:-1:self.samp_int]).astype(int),
                                      np.round(xspline[1:-1:self.samp_int]).astype(int)])

            # Prepare for extracting the profiles
            self.xspline = xspline[1:-1:self.samp_int][pts_mask]
            self.yspline = yspline[1:-1:self.samp_int][pts_mask]
            self.points = np.asarray(zip(self.xspline, self.yspline))
            self.fprime = np.asarray(zip(xprime[1:-1:self.samp_int][pts_mask], yprime[1:-1:self.samp_int][pts_mask]))


            # Extract the profiles
            dictionary_cuts = defaultdict(list)
            if (self.imgscale.unit == u.pc):
                for n in range(len(self.points)):
                    profile = profile_tools.profile_builder(self, self.points[n], self.fprime[n], shift = self.shift, wrap = self.wrap)
                    cut_distance = profile[0]*self.imgscale.to(u.pc).value
                    dictionary_cuts['distance'].append(cut_distance) ## in pc
                    dictionary_cuts['profile'].append(profile[1])
                    dictionary_cuts['plot_peaks'].append(profile[2])
                    dictionary_cuts['plot_cuts'].append(profile[3])
                    dictionary_cuts['mask_width'].append(geometry.LineString(profile[3]).length*self.imgscale.value)

            elif (self.imgscale.unit == u.pix):
                for n in range(len(self.points)):
                    profile = profile_tools.profile_builder(self, self.points[n], self.fprime[n], shift = self.shift, wrap = self.wrap)
                    cut_distance = profile[0]*self.imgscale.to(u.pix).value  ## in pix
                    dictionary_cuts['distance'].append(cut_distance)
                    dictionary_cuts['profile'].append(profile[1])
                    dictionary_cuts['plot_peaks'].append(profile[2])
                    dictionary_cuts['plot_cuts'].append(profile[3])
                    dictionary_cuts['mask_width'].append(geometry.LineString(profile[3]).length)


            # Return the complete set of cuts. Including those outside `cutdist`.
            self.dictionary_cuts = dictionary_cuts
            ## Plot the peak positions if shift
            if self.shift:
                self.ax.plot(np.asarray(dictionary_cuts['plot_peaks'])[:, 0],
                             np.asarray(dictionary_cuts['plot_peaks'])[:, 1],
                             'b.', markersize = 10.,alpha=0.75)
        # if no cutting
        else:
            warnings.warn("The profile builder when cut=False is currently under development, and may fail with large images. Use at your own risk!!!")

            ## warnings.warn if samp_int exists.
            if (self.samp_int is not None):
                self.samp_int = None
                warnings.warn("samp_int is not used. cut is False.")
            ## warnings.warn if shift and/or wrap is True.
            if (self.shift or (not self.wrap)):
                warnings.warn("shift and/or wrap are not used. cut is False.")
                self.shift, self.wrap = False, True

            # Only points within pts_mask AND the original mask are used.
            if (self.pts_mask is not None):
                pts_mask = ((self.pts_mask[np.round(self.ybeforespline).astype(int),
                                           np.round(self.xbeforespline).astype(int)]) &\
                            (self.mask[np.round(self.ybeforespline).astype(int),
                                       np.round(self.xbeforespline).astype(int)]))
            else:
                pts_mask = (self.mask[np.round(self.ybeforespline).astype(int),
                                      np.round(self.xbeforespline).astype(int)])

            # Make the line object with Shapely
            self.points = np.asarray(zip(self.xbeforespline[pts_mask], self.ybeforespline[pts_mask]))
            line = geometry.LineString(self.points)
            self.xspline, self.yspline, self.fprime = None, None, None

            # Make the mask to use for cutdist selection
            ## (masking out the pixels that are closest to the head or the tail)
            xspine, yspine = self.xbeforespline, self.ybeforespline
            xgrid, ygrid = np.meshgrid(np.arange(self.filspine.shape[1]), np.arange(self.filspine.shape[0]))
            agrid = np.argmin(np.array([np.hypot(xgrid-xspine[i], ygrid-yspine[i]) for i in range(len(xspine))]),
                              axis = 0)
            mask_agrid = (agrid != agrid.max()) & (agrid != 0)

            ## Plot the results #####
            ## prepare
            vmin, vmax = np.min(self.image[self.mask]), np.nanpercentile(self.image[self.mask], 98.)
            xmin, xmax = np.where(self.mask)[1].min(), np.where(self.mask)[1].max()
            ymin, ymax = np.where(self.mask)[0].min(), np.where(self.mask)[0].max()
            ## plot
            fig=plt.figure(figsize=(10, 5))
            ax=plt.gca()
            ax.imshow(self.image,
                      origin='lower',
                      cmap='gray',
                      interpolation='none',
                      norm = colors.LogNorm(vmin = vmin, vmax =  vmax))
            ax.contourf(self.mask,
                        levels = [0., .5],
                        colors = 'w')
            ax.plot(line.xy[0], line.xy[1], 'r', label='fit', lw=2, alpha=0.25)
            ax.set_xlim(max(0., xmin-.1*(xmax-xmin)), min(self.mask.shape[1]-.5, xmax+.1*(xmax-xmin)))
            ax.set_ylim(max(0., ymin-.1*(ymax-ymin)), min(self.mask.shape[0]-.5, ymax+.1*(ymax-ymin)))
            ax.set_xticklabels([])
            ax.set_yticklabels([])
            self.fig, self.ax = fig, ax

            # Extract the distances and the heights
            dictionary_cuts = {}
            if (self.imgscale.unit == u.pc):
                dictionary_cuts['distance'] = [[line.distance(geometry.Point(coord))*self.imgscale.to(u.pc).value for coord in zip(np.where(mask_agrid)[1], np.where(mask_agrid)[0])]]
                dictionary_cuts['profile'] = [[self.image[coord[1], coord[0]] for coord in zip(np.where(mask_agrid)[1], np.where(mask_agrid)[0])]]
                dictionary_cuts['plot_peaks'] = None
                dictionary_cuts['plot_cuts'] = None

            elif (self.imgscale.unit == u.pix):
                dictionary_cuts['distance'] = [[line.distance(geometry.Point(coord))*self.imgscale.to(u.pix).value for coord in zip(np.where(mask_agrid)[1], np.where(mask_agrid)[0])]]
                dictionary_cuts['profile'] = [[self.image[coord[1], coord[0]] for coord in zip(np.where(mask_agrid)[1], np.where(mask_agrid)[0])]]
                dictionary_cuts['plot_peaks'] = None
                dictionary_cuts['plot_cuts'] = None

            self.dictionary_cuts = dictionary_cuts


        xall, yall = np.concatenate(self.dictionary_cuts['distance']),\
                     np.concatenate(self.dictionary_cuts['profile'])

        ## Store the values.
        self.xall = xall ## in pc
        self.yall = yall

        ### the following operations, including binning and fitting, should be done on self.xall and self.yall.
        # Bin the profiles (if nobins=False) or stack the profiles (if nobins=True)
        ## This step assumes linear binning.
        ## If the input is the number of bins:
        if isinstance(bins, numbers.Number) and (bins%1 == 0):
            self.binning = True
            bins = int(round(bins))
            minR, maxR = np.min(self.xall), np.max(self.xall)
            bins = np.linspace(minR, maxR, bins+1)
            masterx = bins[:-1]+.5*np.diff(bins)
            mastery = np.asarray([np.nanmedian(self.yall[((self.xall >= (X-.5*np.diff(bins)[0]))&\
                                  (self.xall < (X+.5*np.diff(bins)[0])))]) for X in masterx])

            # record the number of samples in each bin
            masternobs = np.asarray([np.sum(((self.xall >= (X-.5*np.diff(bins)[0]))&\
                                  (self.xall < (X+.5*np.diff(bins)[0])))) for X in masterx])

            self.bins = bins
        ## If the input is the edges of bins:
        elif isinstance(bins, np.ndarray) and (bins.ndim == 1):
            self.binning = True
            bins = bins
            masterx = bins[:-1]+.5*np.diff(bins) ## assumes linear binning.
            mastery = np.asarray([np.nanmedian(self.yall[((self.xall >= (X-.5*np.diff(bins)[0]))&\
                                  (self.xall < (X+.5*np.diff(bins)[0])))]) for X in masterx])

            # record the number of samples in each bin
            masternobs = np.asarray([np.sum(((self.xall >= (X-.5*np.diff(bins)[0]))&\
                                  (self.xall < (X+.5*np.diff(bins)[0])))) for X in masterx])

            self.bins = bins
        ## If the input is not bins-like.
        else:
            self.binning = False
            self.bins = None
            masterx = self.xall
            mastery = self.yall
            masternobs = None
            print "No binning is applied."

        # Return the profile sent to `fit_profile`.
        self.masterx = masterx
        self.mastery = mastery
        self.masternobs = masternobs

        # Return a dictionary to store the key setup Parameters
        self._params['__init__']['image'] = self.image
        self._params['__init__']['mask'] = self.mask ## This is the intersection between all the masks
        params = {'cutting': self.cutting,
                  'binning': self.binning,
                  'shift': self.shift,
                  'wrap': self.wrap,
                  'bins': self.bins,
                  'samp_int': self.samp_int}
        self._params['build_profile'] = params

        # Return a dictionary to store the results
        ## "points" are the spline points used for the cuts or
        ## the point collection of the original spine in the
        ## "no-cutting" case.
        ## "dictionary_cuts" are for plotting, mainly.
        results = {'points': self.points,
                   'xall': self.xall,
                   'yall': self.yall,
                   'masterx': self.masterx,
                   'mastery': self.mastery,
                   'dictionary_cuts': self.dictionary_cuts}
        self._results['build_profile'] = results

        return self

    def fit_profile(self, bgdist = None, fitdist = None, fitfunc=None, verbose=False, beamwidth=None, bgdegree = 1):

        """
        Fit a model to the filament's master profile

        Parameters
        ------
        self: An instance of the radfil_class

        fitdist: number-like or tuple-like with a length of 2
            The radial distance (in units of pc) out to which you'd like to fit your profile.

            When the input has a length of 2, data points with distances between the two values will be
            used in the fitting.  The negative direction is always to the left of the spline direction,
            which always runs from smaller axis-0 indices to larger axis-0 indices.

        bgdist: tuple-like, with a shape (2,)
            The radial distance range that defines the data points to be used in background subtraction; if None no background is fit

        fitfunc: string
            Options include "Gaussian" or "Plummer"

        bgdegree: integer (default = 1)
            The order of the polynomial used in background subtraction (options are 1 or 0).  Active only when wrap = False.

        beamwidth: float or int
            If not inputed into the make_fil_spine method, beamwidth needs to be provided to calculate deconvolved FWHM of Gaussian/Plummer Fits
            If not provided, deconvolved FWHM values will be set to nan

        Attributes
        ------

        xbg, ybg: 1D numpy.ndarray (list-like)
            Data used for background subtraction.

        xfit, yfit: 1D numpy.ndarray (list-like)
            Data used in fitting.

        bgfit: astropy.modeling.functional_models (1st-order) or float (0th-order)
            The background removal information.

        profilefit: astropy.modeling.functional_models
            The fitting results.

        """

        #Check to make sure user entered valid function
        if isinstance(fitfunc, str):
            if (fitfunc.lower() == 'plummer') or (fitfunc.lower() == 'gaussian'):
                self.fitfunc = fitfunc.lower()
                fitfunc_style = self.fitfunc.capitalize()
            else:
                raise ValueError("Reset fitfunc; You have not entered a valid function. Input 'Gaussian' or 'Plummer'")
        else:
            raise ValueError("Set a fitfunc; You have not entered a valid function. Input 'Gaussian' or 'Plummer'")

        #Check whether beamwidth already exists, or whether they have inputed one here to compute deconvolved FWHM
        if (hasattr(self,'beamwith')==False) & (type(beamwidth)!=None):
            if isinstance(beamwidth, numbers.Number):
                if (self.header is not None):
                    self.beamwidth = beamwidth * u.arcsec
                else:
                    self.beamwidth = beamwidth * u.pix
            else:
                self.beamwidth = None

        # Mask for bg removal
        ## take only bgdist, which should be a 2-tuple or 2-list
        if np.asarray(bgdist).shape == (2,):
            self.bgdist = np.sort(bgdist)
            ## below can be merged... ##########
            if self.wrap:
                maskbg = ((self.masterx >= self.bgdist[0])&\
                          (self.masterx < self.bgdist[1])&\
                          np.isfinite(self.mastery))
            else:
                maskbg = ((abs(self.masterx) >= self.bgdist[0])&\
                          (abs(self.masterx) < self.bgdist[1])&\
                          np.isfinite(self.mastery))

            if sum(maskbg) == 0.:
                raise ValueError("Reset bgdist; there is no data to fit for the background.")
        else:
            self.bgdist = None
            warnings.warn("No background removal will be performed.")

        # Mask for fitting
        ## Anything inside `fitdist` pc is used in fitting.
        if isinstance(fitdist, numbers.Number):
            self.fitdist = fitdist
            mask = ((self.masterx >= (-self.fitdist))&\
                    (self.masterx < self.fitdist)&\
                    np.isfinite(self.mastery))
            if sum(mask) == 0.:
                raise ValueError("Reset fitdist; there is no data inside fitdist.")
        elif np.asarray(fitdist).shape == (2,):
            self.fitdist = np.sort(fitdist)
            mask = ((self.masterx >= self.fitdist[0])&\
                    (self.masterx < self.fitdist[1])&\
                    np.isfinite(self.mastery))
            if sum(mask) == 0.:
                raise ValueError("Reset fitdist; there is no data inside fitdist.")
        ## Fit all data if no fitdist
        else:
            self.fitdist = None
            ## Just fool-proof
            mask = (np.isfinite(self.masterx)&\
                    np.isfinite(self.mastery))
            if sum(mask) == 0.:
                raise ValueError("Reset fitdist; there is no data inside fitdist.")

        # Fit for the background, and remove
        ## If bgdist (yes, background removal.)
        if np.asarray(self.bgdist).shape == (2,):
            ## In the case where the profile is wrapped, simply take the mean in the background.
            ## This is because that a linear fit (with a slope) with only one side is not definite.
            if self.wrap:
                xbg, ybg = self.masterx, self.mastery
                xbg, ybg = xbg[maskbg], ybg[maskbg]
                self.xbg, self.ybg = xbg, ybg
                self.bgfit = models.Polynomial1D(degree = 0,
                                                 c0 = np.median(self.ybg)) ### No fitting!
                self.ybg_filtered = None ## no filtering during background removal
                ## Remove bg without fitting (or essentially a constant fit).
                xfit, yfit = self.masterx[mask], self.mastery[mask]
                yfit = yfit - self.bgfit(xfit) ##########
                ## pass nobs to fitter; masked
                if self.binning:
                    self.nobsfit = self.masternobs[mask]
                else:
                    self.nobsfit = None
                print "The profile is wrapped. Use the 0th order polynomial in BG subtraction."
            ## A first-order bg removal is carried out only when the profile is not wrapped.
            else:
                ## Fit bg
                xbg, ybg = self.masterx, self.mastery
                xbg, ybg = xbg[maskbg], ybg[maskbg]
                self.xbg, self.ybg = xbg, ybg
                bg_init = models.Polynomial1D(degree = bgdegree) ##########
                fit_bg = fitting.LinearLSQFitter()

                ## outlier removal; use sigma clipping, set to 3 sigmas
                fit_bg_or = fitting.FittingWithOutlierRemoval(fit_bg, sigma_clip,
                                                              niter=10, sigma=3.)
                bg = fit_bg(bg_init, self.xbg, self.ybg)
                data_or, bg_or = fit_bg_or(bg_init, self.xbg, self.ybg)
                self.bgfit = bg_or.copy()
                self.ybg_filtered = data_or ## a masked array returned by the outlier removal

                ## Remove bg and prepare for fitting
                xfit, yfit = self.masterx[mask], self.mastery[mask]
                yfit = yfit - self.bgfit(xfit)
                ## pass nobs to fitter; masked
                if self.binning:
                    self.nobsfit = self.masternobs[mask]
                else:
                    self.nobsfit = None

        ## If no bgdist
        else:
            self.bgfit = None
            self.xbg, self.ybg = None, None
            self.ybg_filtered = None
            ## Set up fitting without bg removal.
            xfit, yfit = self.masterx[mask], self.mastery[mask]
            ## pass nobs to fitter; masked
            if self.binning:
                self.nobsfit = self.masternobs[mask]
            else:
                self.nobsfit = None
        self.xfit, self.yfit = xfit, yfit

        # Fit Model
        ## Gaussian model
        if self.fitfunc == "gaussian":
            g_init = models.Gaussian1D(amplitude = .8*np.max(self.yfit),
                                    mean = 0.,
                                    stddev=np.std(self.xfit),
                                    fixed = {'mean': True},
                                    bounds = {'amplitude': (0., np.inf),
                                             'stddev': (0., np.inf)})
            fit_g = fitting.LevMarLSQFitter()
            if self.binning:
                g = fit_g(g_init, self.xfit, self.yfit, weights = self.nobsfit)
            else:
                g = fit_g(g_init, self.xfit, self.yfit)
            self.profilefit = g.copy()
            print '==== Gaussian ===='
            print 'amplitude: %.3E'%self.profilefit.parameters[0]
            print 'width: %.3f'%self.profilefit.parameters[2]
        ## Plummer-like model
        elif self.fitfunc == "plummer":
            g_init = Plummer1D(amplitude = .8*np.max(self.yfit),
                            powerIndex=2.,
                            flatteningRadius = np.std(self.xfit))

            fit_g = fitting.LevMarLSQFitter()
            if self.binning:
                g = fit_g(g_init, self.xfit, self.yfit, weights = self.nobsfit)
            else:
                g = fit_g(g_init, self.xfit, self.yfit)
            self.profilefit = g.copy()
            self.profilefit.parameters[2] = abs(self.profilefit.parameters[2]) #Make sure R_flat always positive
            print '==== Plummer-like ===='
            print 'amplitude: %.3E'%self.profilefit.parameters[0]
            print 'p: %.3f'%self.profilefit.parameters[1]
            print 'R_flat: %.3f'%self.profilefit.parameters[2]

        else:
            raise ValueError("Reset fitfunc; no valid function entered. Options include 'Gaussian' or 'Plummer'")


        ### Plot background fit if bgdist is not none ###
        if self.bgdist is not None:
            fig, ax = plt.subplots(figsize = (8, 8.), ncols = 1, nrows = 2)
            axis = ax[0]

            #Adjust axes limits
            xlim=np.max(np.absolute([np.nanpercentile(self.xall[np.isfinite(self.yall)],1),np.nanpercentile(self.xall[np.isfinite(self.yall)],99)]))
            if not self.wrap:
                axis.set_xlim(-xlim,+xlim)
            else:
                axis.set_xlim(0., +xlim)
            axis.set_ylim(np.nanpercentile(self.yall,0)-np.abs(0.5*np.nanpercentile(self.yall,0)),np.nanpercentile(self.yall,99.9)+np.abs(0.25*np.nanpercentile(self.yall,99.9)))

            axis.plot(self.xall, self.yall, 'k.', markersize = 1., alpha = .1)

            ##########
            if self.binning:
                plotbinx, plotbiny = np.ravel(zip(self.bins[:-1], self.bins[1:])), np.ravel(zip(self.mastery, self.mastery))
                axis.plot(plotbinx, plotbiny,
                          'r-')

            # Plot the range
            plot_bgdist = self.bgdist.copy()
            plot_bgdist[~np.isfinite(plot_bgdist)] = np.asarray(axis.get_xlim())[~np.isfinite(plot_bgdist)]
            axis.fill_between(plot_bgdist, *axis.get_ylim(),
                              facecolor = (0., 1., 0., .05),
                              edgecolor = 'g',
                              linestyle = '--',
                              linewidth = 1.)
            axis.fill_between(-plot_bgdist, *axis.get_ylim(),
                              facecolor = (0., 1., 0., .05),
                              edgecolor = 'g',
                              linestyle = '--',
                              linewidth = 1.)
            axis.plot(np.linspace(axis.get_xlim()[0],axis.get_xlim()[1],200), self.bgfit(np.linspace(axis.get_xlim()[0],axis.get_xlim()[1],200)),'g-', lw=3)
            axis.set_xticklabels([])
            axis.tick_params(labelsize=14)

            xplot = self.xall
            yplot = self.yall - self.bgfit(xplot)


            #Add labels#
            if self.bgfit.degree == 1:
                axis.text(0.03, 0.95,"y=({:.2E})x+({:.2E})".format(self.bgfit.parameters[1],self.bgfit.parameters[0]),ha='left',va='top', fontsize=14, fontweight='bold',transform=axis.transAxes)#,bbox={'facecolor':'white', 'edgecolor':'none', 'alpha':1.0, 'pad':1})
            elif self.bgfit.degree == 0:
                axis.text(0.03, 0.95,"y=({:.2E})".format(self.bgfit.c0.value),ha='left',va='top', fontsize=14, fontweight='bold',transform=axis.transAxes)
            else:
                warnings.warn("Labeling BG functions of higher degrees during plotting are not supported yet.")
            axis.text(0.97, 0.95,"Background\nFit", ha='right',va='top', fontsize=20, fontweight='bold',color='green',transform=axis.transAxes)#,bbox={'facecolor':'white', 'edgecolor':'none', 'alpha':1.0, 'pad':1})

            axis=ax[1]

        else:
            fig, ax = plt.subplots(figsize = (8, 4.), ncols = 1, nrows = 1)
            axis = ax

            xplot=self.xall
            yplot=self.yall


        ## Plot model
        #Adjust axis limit based on percentiles of data
        xlim=np.max(np.absolute([np.nanpercentile(self.xall[np.isfinite(self.yall)],1),np.nanpercentile(self.xall[np.isfinite(self.yall)],99)]))
        if not self.wrap:
            axis.set_xlim(-xlim,+xlim)
        else:
            axis.set_xlim(0., +xlim)
        axis.set_ylim(np.nanpercentile(yplot,0)-np.abs(0.5*np.nanpercentile(yplot,0)),np.nanpercentile(yplot,99.9)+np.abs(0.25*np.nanpercentile(yplot,99.9)))


        axis.plot(xplot, yplot, 'k.', markersize = 1., alpha = .1)
        if self.binning:
            if self.bgdist is not None:
                plotbinx, plotbiny = np.ravel(zip(self.bins[:-1], self.bins[1:])), np.ravel(zip(self.mastery-self.bgfit(self.masterx), self.mastery-self.bgfit(self.masterx)))
            else:
                plotbinx, plotbiny = np.ravel(zip(self.bins[:-1], self.bins[1:])), np.ravel(zip(self.mastery, self.mastery))
            axis.plot(plotbinx, plotbiny,
                      'r-')

        # Plot the range
        if self.fitdist is not None:
            ## symmetric fitting range
            if isinstance(self.fitdist, numbers.Number):
                axis.fill_between([-self.fitdist, self.fitdist], *axis.get_ylim(),
                                  facecolor = (0., 0., 1., .05),
                                  edgecolor = 'b',
                                  linestyle = '--',
                                  linewidth = 1.)
            ## asymmetric fitting range
            elif np.asarray(self.fitdist).shape == (2,):
                plot_fitdist = self.fitdist.copy()
                plot_fitdist[~np.isfinite(plot_fitdist)] = np.asarray(axis.get_xlim())[~np.isfinite(plot_fitdist)]
                axis.fill_between(plot_fitdist, *axis.get_ylim(),
                                  facecolor = (0., 0., 1., .05),
                                  edgecolor = 'b',
                                  linestyle = '--',
                                  linewidth = 1.)
        ## no fitting range; all data are used
        else:
            axis.fill_between(axis.get_xlim(), *axis.get_ylim(),
                              facecolor = (0., 0., 1., .05),
                              edgecolor = 'b',
                              linestyle = '--',
                              linewidth = 1.)

        # Plot the predicted curve
        axis.plot(np.linspace(axis.get_xlim()[0],axis.get_xlim()[1],200), self.profilefit(np.linspace(axis.get_xlim()[0],axis.get_xlim()[1],200)), 'b-', lw = 3., alpha = .6)


        axis.text(0.03, 0.95,"{}={:.2E}\n{}={:.2f}\n{}={:.2f}".format(self.profilefit.param_names[0],self.profilefit.parameters[0],self.profilefit.param_names[1],self.profilefit.parameters[1],self.profilefit.param_names[2],self.profilefit.parameters[2]),ha='left',va='top', fontsize=14, fontweight='bold',transform=axis.transAxes)#,bbox={'facecolor':'white', 'edgecolor':'none', 'alpha':1.0, 'pad':1})
        axis.text(0.97, 0.95,"{}\nFit".format(fitfunc_style), ha='right',va='top', fontsize=20, color='blue',fontweight='bold',transform=axis.transAxes)#,bbox={'facecolor':'white', 'edgecolor':'none', 'alpha':1.0, 'pad':1})
        axis.tick_params(labelsize=14)

        #add axis info
        fig.tight_layout()
        fig.subplots_adjust(hspace=0)
        fig.text(0.5, -0.05, "Radial Distance ({})".format(str(self.imgscale.unit)),fontsize=25,ha='center')
        fig.text(-0.05, 0.5, "Profile Height",fontsize=25,va='center',rotation=90)

        # Return a dictionary to store the key setup Parameters
        params = {'bgdist': self.bgdist,
                  'fitdist': self.fitdist,
                  'fitfunc': self.fitfunc}
        self._params['fit_profile'] = params

        # Return a dictionary to store the results
        ## All the fits are `astropy.model` objects.
        results = {'bgfit': self.bgfit,
                   'profilefit': self.profilefit,
                   'xbg': self.xbg,
                   'ybg': self.ybg,
                   'xfit': self.xfit,
                   'yfit': self.yfit}
        self._results['fit_profile'] = results

        if self.fitfunc == "gaussian":
            FWHM = 2.*np.sqrt(2.*np.log(2.))*self.profilefit.parameters[2]

            if self.beamwidth is not None:

                if (self.beamwidth.unit == u.arcsec) and (self.imgscale_ang is not None):
                    beamwidth_phys = (self.beamwidth/self.imgscale_ang).decompose()*self.imgscale.value
                    print 'Physical Size of the Beam:', beamwidth_phys*self.imgscale.unit

                    if np.isfinite(np.sqrt(FWHM**2.-beamwidth_phys**2.)):
                        FWHM_deconv = np.sqrt(FWHM**2.-beamwidth_phys**2.).value
                    else:
                        FWHM_deconv = np.nan
                        warnings.warn("The Gaussian width is not resolved.")

                elif (self.beamwidth.unit == u.pix):
                    beamwidth_phys = self.beamwidth.value
                    print 'Beamwidth in the Pixel Unit:', self.beamwidth

                    if np.isfinite(np.sqrt(FWHM**2.-beamwidth_phys**2.)):
                        FWHM_deconv = np.sqrt(FWHM**2.-beamwidth_phys**2.).value
                    else:
                        FWHM_deconv = np.nan
                        warnings.warn("The width is not resolved.")
                else:
                    FWHM_deconv = np.nan
                    warnings.warn("A beamwidth is not found. Deconvolved FWHMs cannot be derived.")

            else:
                    FWHM_deconv = np.nan
                    warnings.warn("A beamwidth is not found. Deconvolved FWHMs cannot be derived.")


        if self.fitfunc == "plummer":

            FWHM = 2.*self.profilefit.parameters[2]*np.sqrt(2.**(2./(self.profilefit.parameters[1]-1.)) - 1.)

            if self.beamwidth is not None:
                if (self.beamwidth.unit == u.arcsec) and (self.imgscale_ang is not None):
                    beamwidth_phys = (self.beamwidth/self.imgscale_ang).decompose()*self.imgscale.value
                    print 'Physical Size of the Beam:', beamwidth_phys*self.imgscale.unit

                    if np.isfinite(np.sqrt(FWHM**2.-beamwidth_phys**2.)):
                        FWHM_deconv = np.sqrt(FWHM**2.-beamwidth_phys**2.).value
                    else:
                        FWHM_deconv = np.nan
                        warnings.warn("The width is not resolved.")

                elif (self.beamwidth.unit == u.pix):
                    beamwidth_phys = self.beamwidth.value
                    print 'Beamwidth in the Pixel Unit:', self.beamwidth

                    if np.isfinite(np.sqrt(FWHM**2.-beamwidth_phys**2.)):
                        FWHM_deconv = np.sqrt(FWHM**2.-beamwidth_phys**2.).value
                    else:
                        FWHM_deconv = np.nan
                        warnings.warn("The width is not resolved.")
                else:
                    FWHM_deconv = np.nan
                    warnings.warn("A beamwidth is not found. Deconvolved FWHMs cannot be derived.")
            else:
                FWHM_deconv = np.nan
                warnings.warn("A beamwidth is not found. Deconvolved FWHMs cannot be derived.")

        self.FWHM, self.FWHM_deconv = FWHM, FWHM_deconv
        self._results['FWHM'] = FWHM
        self._results['FWHM_deconv'] = FWHM_deconv

        return self


    def plotter(self):
        '''
        Return a `radfil.plot.RadFilPlotter` class.
        '''
        #print "This is a feature under active development. Use at your own risk."

        from radfil import plot
        return plot.RadFilPlotter(self)
