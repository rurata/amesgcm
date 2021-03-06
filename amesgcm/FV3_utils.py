import numpy as np
from netCDF4 import Dataset
import os

def fms_press_calc(psfc,ak,bk,lev_type='full'):
    """
    Return the 3d pressure field from the surface pressure and the ak/bk coefficients.

    Args:
        psfc: the surface pressure in [Pa] or array of surface pressures 1D or 2D, or 3D (if time dimension)
        ak: 1st vertical coordinate parameter
        bk: 2nd vertical coordinate parameter
        lev_type: "full" (centers of the levels) or "half" (layer interfaces)
                  Default is "full"
    Returns:
        The 3D pressure field at the full PRESS_f(Nk-1:,:,:) or half levels PRESS_h(Nk,:,:,) in [Pa]
    --- 0 --- TOP        ========  p_half
    --- 1 ---                    
                         --------  p_full
    
                         ========  p_half
    ---Nk-1---           --------  p_full
    --- Nk --- SFC       ========  p_half 
                        / / / / /
    
    *NOTE* 
        Some litterature uses pk (pressure) instead of ak. 
        With p3d=  ps*bk +pref*ak  vs the current  p3d= ps*bk +ak      
        
         
    """
    #Ignore division by zero warning for the Legacy GCM
    
    Nk=len(ak)
    # If psfc is a float (e.g. psfc=7.) make it a one element array (e.g. psfc=[7.])
    if len(np.atleast_1d(psfc))==1: psfc=np.array([np.squeeze(psfc)])
        
    #Flatten the pressure array to generalize to N dimensions
    psfc_flat=psfc.flatten()
    
    # Expands the dimensions vectorized calculations: 
    psfc_v=np.repeat(psfc_flat[:,np.newaxis],Nk, axis=1)    #(Np) ->(Np,Nk)
    ak_v=np.repeat(ak[np.newaxis,:],len(psfc_flat), axis=0) #(Nk) ->(Np,Nk)
    bk_v=np.repeat(bk[np.newaxis,:],1, axis=0)              #(Nk) ->(1, Nk)
    
    #Pressure at half level = layers interfaces. The size of z axis is Nk
    PRESS_h=psfc_v*bk_v+ak_v
    
    #Pressure at full levels = centers of the levels. The size of z axis is Nk-1
    PRESS_f=np.zeros((len(psfc_flat),Nk-1))
    #Top layer (1st element is i=0 in Python)
    if ak[0]==0 and bk[0]==0: 
        PRESS_f[:,0]= 0.5*(PRESS_h[:,0]+PRESS_h[:,1])
    else:
        PRESS_f[:,0] = (PRESS_h[:,1]-PRESS_h[:,0])/np.log(PRESS_h[:,1]/PRESS_h[:,0])

    #Rest of the column (i=1..Nk).
    #[2:] goes from the 3rd element to Nk and [1:-1] goes from the 2nd element to Nk-1
    PRESS_f[:,1:]= (PRESS_h[:,2:]-PRESS_h[:,1:-1])/np.log(PRESS_h[:,2:]/PRESS_h[:,1:-1])

    # First transpose PRESS(:,Nk) to PRESS(Nk,:), then reshape PRESS(Nk,:) 
    # to the original pressure shape PRESS(Nk,:,:,:) (resp. Nk-1)
                       
    if lev_type=="full":
        new_dim_f=np.append(Nk-1,psfc.shape)
        return np.squeeze(PRESS_f.T.reshape(new_dim_f)) 
    elif lev_type=="half" :  
        new_dim_h=np.append(Nk,psfc.shape)
        return np.squeeze(PRESS_h.T.reshape(new_dim_h))
    else: 
        raise Exception("""Pressure levels type not recognized in press_lev(): use 'full' or 'half' """)

def fms_Z_calc(psfc,ak,bk,T,topo=0.,lev_type='full'):
    """
    Return the 3d altitude field in [m] above ground level or above aeroid.

    Args:
        psfc: the surface pressure in [Pa] or array of surface pressures 1D or 2D, or 3D 
        ak: 1st vertical coordinate parameter
        bk: 2nd vertical coordinate parameter
        T : the air temperature profile, 1D array (for a single grid point) N-dimensional array with VERTICAL AXIS FIRST
        topo: the surface elevation, same dimension as psfc. If none is provided, the height above ground level (agl) is returned
        lev_type: "full" (centers of the levels) or "half" (layer interfaces)
                  Default is "full"
    Returns:
        The layers' altitude  at the full Z_f(:,:,Nk-1) or half levels Z_h(:,:,Nk) in [m]
        Z_f and Z_h are AGL if topo is None, and above aeroid if topo is provided 
    
    --- 0 --- TOP        ========  z_half
    --- 1 ---                    
                         --------  z_full
    
                         ========  z_half
    ---Nk-1---           --------  z_full
    --- Nk --- SFC       ========  z_half 
                        / / / / /
    
    
    *NOTE* 
        Expends tp the time dimension using topo=np.repeat(zsurf[np.newaxis,:],ps.shape[0],axis=0)
    
        Calculation is derived from ./atmos_cubed_sphere_mars/Mars_phys.F90:
        We have dp/dz = -rho g => dz= dp/(-rho g) and rho= p/(r T)  => dz=rT/g *(-dp/p) 
        Let's define the log-pressure u as u = ln(p). We have du = du/dp *dp = (1/p)*dp =dp/p
        
        Finally , we have dz for the half layers:  dz=rT/g *-(du) => dz=rT/g *(+dp/p)   with N the layers defined from top to bottom.
    """
    g=3.72 #acc. m/s2
    r_co2= 191.00 # kg/mol
    Nk=len(ak)
    #===get the half and full pressure levels from fms_press_calc==
    
    PRESS_f=fms_press_calc(psfc,ak,bk,'full') #Z axis is first
    PRESS_h=fms_press_calc(psfc,ak,bk,'half') #Z axis is first
    
    # If psfc is a float, turn it into a one-element array:
    if len(np.atleast_1d(psfc))==1: 
        psfc=np.array([np.squeeze(psfc)])
    if len(np.atleast_1d(topo))==1:    
        topo=np.array([np.squeeze(topo)])
        
    psfc_flat=psfc.flatten()
    topo_flat=topo.flatten()
    
    #  reshape arrays for vector calculations and compute the log pressure====
    
    PRESS_h=PRESS_h.reshape((Nk  ,len(psfc_flat)))
    PRESS_f=PRESS_f.reshape((Nk-1,len(psfc_flat)))
    T=T.reshape((Nk-1,len(psfc_flat)))
    
    logPPRESS_h=np.log(PRESS_h)
    
    #===Initialize the output arrays===
    Z_f=np.zeros((Nk-1,len(psfc_flat)))
    Z_h=np.zeros((Nk  ,len(psfc_flat)))

    #First half layer is equal to the surface elevation
    
    Z_h[-1,:] = topo_flat
    
    # Other layes, from the bottom-ip:
    for k in range(Nk-2,-1,-1):
        Z_h[k,:] = Z_h[k+1,:]+(r_co2*T[k,:]/g)*(logPPRESS_h[k+1,:]-logPPRESS_h[k,:])
        Z_f[k,:] = Z_h[k+1,:]+(r_co2*T[k,:]/g)*(1-PRESS_h[k,:]/PRESS_f[k,:])
        
    #return the arrays
    if lev_type=="full":
        new_dim_f=np.append(Nk-1,psfc.shape)
        return Z_f.reshape(new_dim_f)
    elif lev_type=="half" : 
        new_dim_h=np.append(Nk,psfc.shape)
        return  Z_h.reshape(new_dim_h)
    #=====return the levels in Z coordinates [m]====
    else: 
        raise Exception("""Altitudes levels type not recognized: use 'full' or 'half' """)
        
def find_n(Lfull,Llev,reverse_input=False):
    '''
    Return the index for the level(s) just below Llev.
    This assumes Lfull increases with increasing e.g p(0)=0Pa, p(N)=1000Pa
    
    Args:
        Lfull (array)            : input pressure [pa] or altitude [m] at full levels, level dimension is FIRST 
        Llev (float or 1D array) : desired level for interpolation [Pa] or [m]
        reverse_input (boolean)  : reverse array, e.g if z(0)=120 km, z(N)=0km (which is typical) or if your input data is p(0)=1000Pa, p(N)=0Pa
    Returns:
        n:    index for the level(s) where the pressure is just below plev.
    ***NOTE***
        - if Lfull is 1D array and  Llev is a float        > n is a float 
        - if Lfull is ND [lev,time,lat,lon] and Llev is a 1D array of size klev > n is an array of size[klev,Ndim]
          with Ndim =time x lat x lon
    '''
                   #number of original layers
    Lfull=np.array(Lfull)               
    Nlev=len(np.atleast_1d(Llev))
    if Nlev==1:Llev=np.array([Llev])
    dimsIN=Lfull.shape                         #get input variable dimensions
    Nfull=dimsIN[0]  
    dimsOUT=tuple(np.append(Nlev,dimsIN[1:]))
    Ndim= np.int(np.prod(dimsIN[1:]))           #Ndim is the product  of all dimensions but the vertical axis
    Lfull= np.reshape(Lfull, (Nfull, Ndim) )  
    
    if reverse_input:Lfull=Lfull[::-1,:]          
       
    ncol=Lfull.shape[-1]
    n=np.zeros((Nlev,ncol),dtype=int)
    
    for i in range(0,Nlev):
        for j in range(0,ncol) :
            n[i,j]=np.argmin(np.abs(Lfull[:,j]-Llev[i]))
            if Lfull[n[i,j],j]>Llev[i]:n[i,j]=n[i,j]-1
    return n



def vinterp(varIN,Lfull,Llev,type='log',reverse_input=False,masktop=True,index=None):
    '''
    Vertical linear or logarithmic interpolation for pressure or altitude.   Alex Kling 5-27-20
    Args:
        varIN: variable to interpolate (N-dimensional array with VERTICAL AXIS FIRST)
        Lfull: pressure [Pa] or atitude [m] at full layers same dimensions as varIN
        Llev : desired level for interpolation as a 1D array in [Pa] or [m] May be either increasing or decreasing as the output levels are processed one at the time.
        reverse_input (boolean) : reverse input arrays, e.g if zfull(0)=120 km, zLfull(N)=0km (which is typical) or if your input data is pfull(0)=1000Pa, pfull(N)=0Pa
        type : 'log' for logarithmic (typically pressure), 'lin' for linear (typically altitude)
        masktop: set to NaN values if above the model top
        index: indices for the interpolation, already procesed as [klev,Ndim] 
               Indices will be recalculated in not provided.
    Returns:
        varOUT: variable interpolated on the Llev pressure or altitude levels
        
    *** IMPORTANT NOTE***
    This interpolation assumes pressure are increasing downward, i.e:   
     
        ---  0  --- TOP   [0 Pa]   : [120 km]|    X_OUT= Xn*A + (1-A)*Xn+1
        ---  1  ---                :         |      
                                   :         |         
        ---  n  ---  pn   [30 Pa]  : [800 m] | Xn
                                   :         |
    >>> ---  k  ---  Llev [100 Pa] : [500 m] | X_OUT       
        --- n+1 ---  pn+1 [200 Pa] : [200 m] | Xn+1
    
        --- SFC ---      
        / / / / / /
        
    with A = log(Llev/pn+1)/log(pn/pn+1) in 'log' mode     
         A =    (zlev-zn+1)/(zn-zn+1)    in 'lin' mode
         
         
    '''
    #Special case where only 1 layer is requested
    Nlev=len(np.atleast_1d(Llev))
    if Nlev==1:Llev=np.array([Llev])
 
    dimsIN=varIN.shape               #get input variable dimensions
    Nfull=dimsIN[0]
    
    #Special case where varIN and Lfull are a single profile            
    if len(varIN.shape )==1:varIN=varIN.reshape([Nfull,1])
    if len(Lfull.shape )==1:Lfull=Lfull.reshape([Nfull,1])
       
    dimsIN=varIN.shape       #repeat in case varIN and Lfull were reshaped
               
    dimsOUT=tuple(np.append(Nlev,dimsIN[1:]))
    Ndim= np.int(np.prod(dimsIN[1:]))          #Ndim is the product  of all dimensions but the vertical axis
    varIN= np.reshape(varIN, (Nfull, Ndim))    #flatten the other dimensions to (Nfull, Ndim)
    Lfull= np.reshape(Lfull, (Nfull, Ndim) )   #flatten the other dimensions to (Nfull, Ndim)
    varOUT=np.zeros((Nlev, Ndim))
    Ndimall=np.arange(0,Ndim)                   #all indices (does not change)
    
    #
    if reverse_input:
        Lfull=Lfull[::-1,:] 
        varIN=varIN[::-1,:]
    
    for k in range(0,Nlev):
        #Find nearest layer to Llev[k]
        if np.any(index):
            #index have been pre-computed:  
            n= index[k,:]
        else:
            # Compute index on the fly for that layer. 
            # Note that inverse_input is always set to False as if desired, Lfull was reversed earlier
            n= np.squeeze(find_n(Lfull,Llev[k],False))
        #==Slower method (but explains what is done below): loop over Ndim======
        # for ii in range(Ndim):
        #     if n[ii]<Nfull-1:
        #         alpha=np.log(Llev[k]/Lfull[n[ii]+1,ii])/np.log(Lfull[n[ii],ii]/Lfull[n[ii]+1,ii])
        #         varOUT[k,ii]=varIN[n[ii],ii]*alpha+(1-alpha)*varIN[n[ii]+1,ii]
        
        #=================    Fast method  no loop  =======================
        #Convert the layers n to indexes, for a 2D matrix using nindex=i*ncol+j
        nindex  =    n*Ndim+Ndimall  # n
        nindexp1=(n+1)*Ndim+Ndimall  # n+1
        
        #initialize alpha, size is [Ndim]
        alpha=np.NaN*Ndimall
        #Only calculate alpha  where the indices are <Nfull
        Ndo=Ndimall[nindexp1<Nfull*Ndim]
        if type=='log':
            alpha[Ndo]=np.log(Llev[k]/Lfull.flatten()[nindexp1[Ndo]])/np.log(Lfull.flatten()[nindex[Ndo]]/Lfull.flatten()[nindexp1[Ndo]])
        elif type=='lin':
            alpha[Ndo]=(Llev[k]-Lfull.flatten()[nindexp1[Ndo]])/(Lfull.flatten()[nindex[Ndo]]- Lfull.flatten()[nindexp1[Ndo]])
            
        #Mask if Llev[k]<model top for the pressure interpolation
        if masktop : alpha[Llev[k]<Lfull.flatten()[nindex]]=np.NaN
       
       
        #Here, we need to make sure n+1 is never> Nfull by setting n+1=Nfull, if it is the case.
        #This does not affect the calculation as alpha is set to NaN for those values. 
        nindexp1[nindexp1>=Nfull*Ndim]=nindex[nindexp1>=Nfull*Ndim]
        
        varOUT[k,:]=varIN.flatten()[nindex]*alpha+(1-alpha)*varIN.flatten()[nindexp1]
        
    return np.reshape(varOUT,dimsOUT)


def cart_to_azimut_TR(u,v,mode='from'):
    '''
    Convert cartesian coordinates or wind vectors to radian,using azimut angle.
    
    Args:
        x,y: 1D arrays for the cartesian coordinate
        mode='to' direction towards the vector is pointing, 'from': direction from the vector is coming
    Returns:
        Theta [deg], R the polar coordinates
    '''
    if mode=='from':cst=180
    if mode=='to':cst=0.    
    return np.mod(np.arctan2(u,v)*180/np.pi+cst,360),np.sqrt(u**2+v**2)
    
        
def sfc_area_deg(lon1,lon2,lat1,lat2,R=3390000.):
    '''
    Return the surface between two set of latitudes/longitudes
    S= Int[R**2 dlon cos(lat) dlat]     _____lat2
    Args:                               \    \
        lon1,lon2: in [degree]           \____\lat1
        lat1,lat2: in [degree]        lon1    lon2
        R: planetary radius in [m]
    *** NOTE***
    Lon and Lat define the corners of the area, not the grid cells' centers
    
    '''
    lat1*=np.pi/180;lat2*=np.pi/180;lon1*=np.pi/180;lon2*=np.pi/180
    return (R**2)*np.abs(lon1-lon2)*np.abs(np.sin(lat1)-np.sin(lat2))


def area_meridional_cells_deg(lat_c,dlon,dlat,normalize=False,R=3390000.):
    '''
    Return area of invidual cells for a medidional band of thickness dlon
    S= Int[R**2 dlon cos(lat) dlat]
    with  sin(a)-sin(b)=2 cos((a+b)/2)sin((a+b)/2)   
    >>> S= 2 R**2 dlon 2 cos(lat)sin(dlat/2)         _________lat+dlat/2
    Args:                                            \    lat \             ^
        lat_c: latitude of cell center in [degree]    \lon +   \            | dlat
        dlon : cell angular width  in [degree]         \________\lat-dlat/2 v
        dlat : cell angular height in [degree]   lon-dlon/2      lon+dlon/2         
        R: planetary radius in [m]                       <------> 
        normalize: if True, sum of output elements is 1.   dlon
    Returns:
        S: areas of the cells, same size as lat_c in [m2] or normalized by the total area
    '''  
    #Initialize
    area_tot=1.
    #Compute total area in a longitude band extending from lat[0]-dlat/2 to lat_c[-1]+dlat/2
    if normalize:
        area_tot= sfc_area_deg(-dlon/2,dlon/2,lat_c[0]-dlat/2,lat_c[-1]+dlat/2,R)
    #Now convert to radians    
    lat_c=lat_c*np.pi/180
    dlon*=np.pi/180
    dlat*=np.pi/180    
    return 2.*R**2*dlon*np.cos(lat_c)*np.sin(dlat/2.)/area_tot

def area_weights_deg(VAR_shape,lat_c,axis=-2):
    '''
    Return weights for averaging of the variable VAR.   
    Args:              
        VAR_shape: Variable's shape, e.g. [133,36,48,46] typically obtained with 'VAR.shape' 
        Expected dimensions are:                      (lat) [axis not need]
                                                 (lat, lon) [axis=-2 or axis=0]
                                           (time, lat, lon) [axis=-2 or axis=1]
                                      (time, lev, lat, lon) [axis=-2 or axis=2]
                           (time, time_of_day_24, lat, lon) [axis=-2 or axis=2]  
                      (time, time_of_day_24, lev, lat, lon) [axis=-2 or axis=3]
                                               
        lat_c: latitude of cell centers in [degree] 
        axis: Position of the latitude axis for 2D and higher-dimensional arrays. The default is the SECOND TO LAST dimension, e.g: axis=-2 
           >>> Because dlat is computed as lat_c[1]-lat_c[0] lat_c may be truncated on either end (e.g. lat= [-20 ...,0... +50]) but must be contineous. 
    Returns:
        W: weights for VAR, ready for standard averaging as np.mean(VAR*W) [condensed form] or np.average(VAR,weights=W) [expended form]

    ***NOTE***
    Given a variable VAR: 
        VAR= [v1,v2,...vn]    
    Regular average is:    
        AVG = (v1+v2+... vn)/N   
    Weighted average is:     
        AVG_W= (v1*w1+v2*w2+... vn*wn)/(w1+w2+...wn)   
        
    This function returns: 
        W= [w1,w2,... ,wn]*N/(w1+w2+...wn)
        
    >>> Therfore taking a regular average of (VAR*W) with np.mean(VAR*W) or np.average(VAR,weights=W) returns the weighted-average of VAR
    Use np.average(VAR,weights=W,axis=X) to average over a specific axis
        
    ''' 
    
    #VAR or lat is a scalar, do nothing
    if len(np.atleast_1d(lat_c))==1 or len(np.atleast_1d(VAR_shape))==1:
        return np.ones(VAR_shape)
    else:
        #Then, lat has at least 2 elements
        dlat=lat_c[1]-lat_c[0]   
        #Calculate cell areas. Since it is normalized, we can use dlon= 1 and R=1 without changing the result
        A=area_meridional_cells_deg(lat_c,1,dlat,normalize=True,R=1) #Note that sum(A)=(A1+A2+...An)=1  
        #VAR is a 1D array. of size (lat). Easiest case since (w1+w2+...wn)=sum(A)=1 and N=len(lat)
        if len(VAR_shape)==1:    
            W= A*len(lat_c)
        else: 
            # Generate the appropriate shape for the area A, e.g  (time, lev, lat, lon) > (1, 1, lat, 1)
            # In this case, N=time*lev*lat*lon and  (w1+w2+...wn) =time*lev*lon*sum(A) , therefore N/(w1+w2+...wn)=lat
            reshape_shape=[1 for i in range(0,len(VAR_shape))]
            reshape_shape[axis]=len(lat_c)
            W= A.reshape(reshape_shape)*len(lat_c)
        return W*np.ones(VAR_shape)

    
def zonal_avg_P_lat(Ls,var,Ls_target,Ls_angle,symmetric=True):
    """
    Return the zonally averaged mean value of a pressure interpolated 4D variable.

    Args:
        Ls: 1D array of solar longitude of the input variable in degree (0->360)
        var: a 4D variable var [time,levels,lat,lon] interpolated on the pressure levels (f_average_plevs file)
        Ls_target: central solar longitude of interest.     
        Ls_angle:  requested window angle centered around   Expl:  Ls_angle = 10.  (Window will go from Ls 85  
        symmetric: a boolean (default =True) If True, and if the requested window is out of range, Ls_angle is reduced
                                             If False, the time average is done on the data available
    Returns:
        The zonnally and latitudinally-averaged field zpvar[level,lat]
    
    Expl:  Ls_target= 90.
           Ls_angle = 10.  
           
           ---> Nominally, the time average is done over solar longitudes      85 <Ls_target < 95 (10 degree)
           
           ---> If  symmetric =True and the input data ranges from Ls 88 to 100     88 <Ls_target < 92 (4  degree, symmetric)
                If  symmetric =False and the input data ranges from Ls 88 to 100    88 <Ls_target < 95 (7  degree, assymetric)
    *NOTE* 
    
    [Alex] as of 6/8/18, the routine will bin data from muliples Mars years if provided
         
    """
    #compute bounds from Ls_target and Ls_angle
    Ls_min= Ls_target-Ls_angle/2.
    Ls_max= Ls_target+Ls_angle/2.
    
    if (Ls_min<0.):Ls_min+=360.
    if (Ls_max>360.):Ls_max-=360. 
    
    #Initialize output array
    zpvar=np.zeros((var.shape[1],var.shape[2])) #nlev, nlat
    
    #check is the Ls of interest is within the data provided, raise execption otherwise
    if Ls_target <= Ls.min() or Ls_target >=Ls.max() :
        raise Exception("Error \nNo data found, requested  data :       Ls %.2f <-- (%.2f)--> %.2f\nHowever, data in file only ranges      Ls %.2f <-- (%.2f)--> %.2f"%(Ls_min,Ls_target,Ls_max,Ls.min(),(Ls.min()+Ls.max())/2.,Ls.max()))

    
    else : #If only some of the requested data is outside the ranges, process this data
        if Ls_min <Ls.min() or Ls_max >Ls.max():
            print("In zonal_avg_P_lat() Warning: \nRequested  data ranging    Ls %.2f <-- (%.2f)--> %.2f"%(Ls_min,Ls_target,Ls_max))
            if symmetric: #Case 1: reduce the window
                if Ls_min <Ls.min():
                    Ls_min =Ls.min()
                    Ls_angle=2*(Ls_target-Ls_min)
                    Ls_max= Ls_target+Ls_angle/2.
                    
                if Ls_max >Ls.max():
                    Ls_max =Ls.max()
                    Ls_angle=2*(Ls_max-Ls_target)
                    Ls_min= Ls_target-Ls_angle/2.
                    
                print("Reshaping data ranging     Ls %.2f <-- (%.2f)--> %.2f"%(Ls_min,Ls_target,Ls_max))        
            else: #Case 2: Use all data available
                print("I am only using            Ls %.2f <-- (%.2f)--> %.2f \n"%(max(Ls.min(),Ls_min),Ls_target,min(Ls.max(),Ls_max)))
    count=0
    #perform longitude average on the field
    zvar= np.mean(var,axis=3)
    
    for t in xrange(len(Ls)):
    #special case Ls around Ls =0 (wrap around)
        if (Ls_min<=Ls[t] <= Ls_max):
            zpvar[:,:]=zpvar[:,:]+zvar[t,:,:]
            count+=1
            
    if  count>0:
        zpvar/=count
    return zpvar
    

    
def alt_KM(press,scale_height_KM=8.,reference_press=610.):
    """
    Gives the approximate altitude in km for a given pressure
    Args:
        press: the pressure in [Pa]
        scale_height_KM: a scale height in [km], (default is 10 km)
        reference_press: reference surface pressure in [Pa], (default is 610 Pa)
    Returns:
        z_KM: the equivalent altitude for that pressure level in [km]
   
    """      
    return -scale_height_KM*np.log(press/reference_press) # p to altitude in km      
    
def press_pa(alt_KM,scale_height_KM=8.,reference_press=610.):
    """
    Gives the approximate altitude in km for a given pressure
    Args:
        alt_KM: the altitude in  [km]
        scale_height_KM: a scale height in [km], (default is 8 km)
        reference_press: reference surface pressure in [Pa], (default is 610 Pa)
    Returns:
         press_pa: the equivalent pressure at that altitude in [Pa]
   
    """      
    return reference_press*np.exp(-alt_KM/scale_height_KM) # p to altitude in km 
     
def lon180_to_360(lon):
    lon=np.array(lon)
    """
    Transform a float or an array from the -180/+180 coordinate system to 0-360
    Args:
        lon: a float, 1D or 2D array of longitudes in the 180/+180 coordinate system
    Returns:
        lon: the equivalent longitudes in the 0-360 coordinate system
   
    """ 
    if len(np.atleast_1d(lon))==1: #lon180 is a float
        if lon<0:lon+=360 
    else:                            #lon180 is an array
        lon[lon<0]+=360
        lon=np.append(lon[lon<180],lon[lon>=180]) #reogranize lon by increasing values
    return lon
    
def lon360_to_180(lon):
    lon=np.array(lon)
    """
    Transform a float or an array from the 0-360 coordinate system to -180/+180
    Args:
        lon: a float, 1D or 2D array of longitudes in the 0-360 coordinate system
    Returns:
        lon: the equivalent longitudes in the -180/+180 coordinate system
   
    """ 
    if len(np.atleast_1d(lon))==1:   #lon is a float
        if lon>180:lon-=360 
    else:                            #lon is an array
        lon[lon>180]-=360
        lon=np.append(lon[lon<0],lon[lon>=0]) #reogranize lon by increasing values
    return lon    
     
def shiftgrid_360_to_180(lon,data): #longitude is LAST
    '''
    This function shift N dimensional data a 0->360 to a -180/+180 grid.
    Args:
        lon: 1D array of longitude 0->360
        data: ND array with last dimension being the longitude (transpose first if necessary)
    Returns:
        data: shifted data
    Note: Use np.ma.hstack instead of np.hstack to keep the masked array properties
    '''
    lon=np.array(lon)
    lon[lon>180]-=360. #convert to +/- 180
    data=np.concatenate((data[...,lon<0],data[...,lon>=0]),axis=-1) #stack data
    return data


def shiftgrid_180_to_360(lon,data): #longitude is LAST
    '''
    This function shift N dimensional data a -180/+180 grid to a 0->360
    Args:
        lon: 1D array of longitude -180/+180
        data: ND array with last dimension being the longitude (transpose first if necessary)
    Returns:
        data: shifted data
    Note: Use np.ma.hstack instead of np.hstack to keep the masked array properties
    '''
    lon=np.array(lon)
    lon[lon<0]+=360. #convert to 0-360
    data=np.concatenate((data[...,lon<180],data[...,lon>=180]),axis=-1) #stack data
    return data
        
def second_hhmmss(seconds,lon_180=0.):
    """
    Given the time seconds return Local true Solar Time at a certain longitude
    Args:
        seconds: a float, the time in seconds
        lon_180: a float, the longitude in -/+180 coordinate
    Returns:
        hours: float, the local time or  (hours,minutes, seconds)
   
    """ 
    hours = seconds // (60*60)
    seconds %= (60*60)
    minutes = seconds // 60
    seconds %= 60
    #Add timezone offset (1hr/15 degree)
    hours=np.mod(hours+lon_180/15.,24)
    
    return np.int(hours), np.int(minutes), np.int(seconds)

def sol_hhmmss(time_sol,lon_180=0.):
    """
    Given the time in days, return the Local true Solar Time at a certain longitude
    Args:
        time_sol: a float, the time, eg. sols 2350.24
        lon_180: a float, the longitude in a -/+180 coordinate
    Returns:
        hours: float, the local time or  (hours,minutes, seconds)
    """ 
    return second_hhmmss(time_sol*86400.,lon_180)


def UT_LTtxt(UT_sol,lon_180=0.,roundmin=None):
    '''
    Returns the time in HH:MM:SS format at a certain longitude. 
    Args:
        time_sol: a float, the time, eg. sols 2350.24
        lon_180: a float, the center longitude in  -/+180 coordinate. Increment by 1hr every 15 deg
        roundmin: round to the nearest X minute  Typical values are roundmin=1,15,60
    ***Note***
    If roundmin is requested, seconds are not shown  
    '''
    def round2num(number,interval):
        # Internal function to round a number to the closest  range.
        # e.g. round2num(26,5)=25 ,round2num(28,5)=30
        return round(number / interval) * interval
    
    
    hh,mm,ss=sol_hhmmss(UT_sol,lon_180)

    if roundmin:
        sec=hh*3600+mm*60+ss
        # Round to the nearest increment (in seconds) and run a second pass
        rounded_sec=round2num(sec,roundmin*60)
        hh,mm,ss=second_hhmmss(rounded_sec,lon_180)
        return '%02d:%02d'%(hh,mm)
    else:
        return '%02d:%02d:%02d'%(hh,mm,ss)
            
     

def space_time(lon,timex, varIN,kmx,tmx):
    """
    Obtain west and east propagating waves. This is a Python implementation of John Wilson's  space_time routine by Alex
    Args:
        lon:   longitude array in [degrees]   0->360 
        timex: 1D time array in units of [day]. Expl 1.5 days sampled every hour is  [0/24,1/24, 2/24,.. 1,.. 1.5]
        varIN: input array for the Fourier analysis.
               First axis must be longitude and last axis must be time.  Expl: varIN[lon,time] varIN[lon,lat,time],varIN[lon,lev,lat,time]
        kmx: an integer for the number of longitudinal wavenumber to extract   (max allowable number of wavenumbers is nlon/2)
        tmx: an integer for the number of tidal harmonics to extract           (max allowable number of harmonics  is nsamples/2)

    Returns:
        ampe:   East propagating wave amplitude [same unit as varIN]
        ampw:   West propagating wave amplitude [same unit as varIN]
        phasee: East propagating phase [degree]
        phasew: West propagating phase [degree]
        
         
   
    *NOTE*  1. ampe,ampw,phasee,phasew have dimensions [kmx,tmx] or [kmx,tmx,lat] [kmx,tmx,lev,lat] etc...
            2. The x and y axis may be constructed as follow to display the easter and western modes:
            
                klon=np.arange(0,kmx)  [wavenumber]  [cycle/sol] 
                ktime=np.append(-np.arange(tmx,0,-1),np.arange(0,tmx)) 
                KTIME,KLON=np.meshgrid(ktime,klon)
                
                amplitude=np.concatenate((ampw[:,::-1], ampe), axis=1)  
                phase=    np.concatenate((phasew[:,::-1], phasee), axis=1)

    """           
    
    dims= varIN.shape             #get input variable dimensions
    
    lon_id= dims[0]    # lon          
    time_id= dims[-1]  # time     
    dim_sup_id=dims[1:-1] #additional dimensions stacked in the middle
    jd= np.int(np.prod( dim_sup_id))     #jd is the total number of dimensions in the middle is varIN>3D
    
    varIN= np.reshape(varIN, (lon_id, jd, time_id) )   #flatten the middle dimensions if any
    
    #Initialize 4 empty arrays
    ampw, ampe,phasew,phasee =[np.zeros((kmx,tmx,jd)) for _x in range(0,4)]
    
    #TODO not implemented yet: zamp,zphas=[np.zeros((jd,tmx)) for _x in range(0,2)] 
    
    tpi= 2*np.pi
    argx= lon * 2*np.pi/360  #nomalize longitude array
    rnorm= 2./len(argx)
    
    arg= timex * 2* np.pi
    rnormt= 2./len(arg)
    
    #
    for kk in range(0,kmx): 
        progress(kk,kmx) 
        cosx= np.cos( kk*argx )*rnorm
        sinx= np.sin( kk*argx )*rnorm
        
    #   Inner product to calculate the Fourier coefficients of the cosine
    #   and sine contributions of the spatial variation
        acoef = np.dot(varIN.T,cosx) 
        bcoef = np.dot(varIN.T,sinx)

    # Now get the cos/sine series expansions of the temporal
    #variations of the acoef and bcoef spatial terms.
        for nn in range(0,tmx):
            cosray= rnormt*np.cos(nn*arg )
            sinray= rnormt*np.sin(nn*arg )
        
            cosA=  np.dot(acoef.T,cosray)
            sinA=  np.dot(acoef.T,sinray)
            cosB=  np.dot(bcoef.T,cosray)
            sinB=  np.dot(bcoef.T,sinray)
        
        
            wr= 0.5*(  cosA - sinB )
            wi= 0.5*( -sinA - cosB )
            er= 0.5*(  cosA + sinB )
            ei= 0.5*(  sinA - cosB )
        
            aw= np.sqrt( wr**2 + wi**2 )
            ae= np.sqrt( er**2 + ei**2)
            pe= np.arctan2(ei,er) * 180/np.pi
            pw= np.arctan2(wi,wr) * 180/np.pi
        
            pe= np.mod( -np.arctan2(ei,er) + tpi, tpi ) * 180/np.pi
            pw= np.mod( -np.arctan2(wi,wr) + tpi, tpi ) * 180/np.pi
        
            ampw[kk,nn,:]= aw.T
            ampe[kk,nn,:]= ae.T
            phasew[kk,nn,:]= pw.T
            phasee[kk,nn,:]= pe.T
    #End loop
    
    
    ampw=   np.reshape( ampw,    (kmx,tmx)+dim_sup_id )
    ampe=   np.reshape( ampe,    (kmx,tmx)+dim_sup_id )
    phasew= np.reshape( phasew,  (kmx,tmx)+dim_sup_id )
    phasee= np.reshape( phasee,  (kmx,tmx)+dim_sup_id )

    #TODO implement zonal mean: zamp,zphas,stamp,stphs
    '''
    #  varIN= reshape( varIN, dims );
    
    #if nargout < 5;  return;  end ---> only  ampe,ampw,phasee,phasew are requested
    
    
    #   Now calculate the axisymmetric tides  zamp,zphas
    
    zvarIN= np.mean(varIN,axis=0)
    zvarIN= np.reshape( zvarIN, (jd, time_id) )
    
    arg= timex * 2* np.pi
    arg= np.reshape( arg, (len(arg), 1 ))
    rnorm= 2/time_id
    
    for nn in range(0,tmx):
        cosray= rnorm*np.cos( nn*arg )
        sinray= rnorm*np.sin( nn*arg )
    
        cosser=  np.dot(zvarIN,cosray)
        sinser=  np.dot(zvarIN,sinray)
    
        zamp[:,nn]= np.sqrt( cosser[:]**2 + sinser[:]**2 ).T
        zphas[:,nn]= np.mod( -np.arctan2( sinser, cosser )+tpi, tpi ).T * 180/np.pi
    
    
    zamp=  zamp.T #np.permute( zamp,  (2 1) )
    zphas= zphas.T #np.permute( zphas, (2,1) )
    
    if len(dims)> 2:
        zamp=  np.reshape( zamp,  (tmx,)+dim_sup_id )
        zamp=  np.reshape( zphas, (tmx,)+dim_sup_id ) 
    
    
    
    #if nargout < 7;  return;  end
    
    sxx= np.mean(varIN,ndims(varIN));
    [stamp,stphs]= amp_phase( sxx, lon, kmx );
    
    if len(dims)> 2;
        stamp= reshape( stamp, [kmx dims(2:end-1)] );
        stphs= reshape( stphs, [kmx dims(2:end-1)] );
    end

    '''
    
    return ampe,ampw,phasee,phasew


        
def dvar_dh(arr, h=None): 
    '''
    Differentiate an array A(dim1,dim2,dim3...) with respect to h. The differentiated dimension must be the first dimension.
    > If h is 1D: h and dim1 must have the same length 
    > If h is 2D, 3D or 4D, arr and h must have the same shape
    Args:
        arr:   an array of dimension n
        h:     the dimension, eg Z, P, lat, lon

    Returns:
        d_arr: the array differentiated with respect to h, e.g d(array)/dh
        
    *Example*
     #Compute dT/dz where T[time,LEV,lat,lon] is the temperature and Zkm is the array of  level heights in Km:
     #First we transpose t so the vertical dimension comes first as T[LEV,time,lat,lon] and then we transpose back to get dTdz[time,LEV,lat,lon].
     dTdz=dvar_dh(t.transpose([1,0,2,3]),Zkm).transpose([1,0,2,3]) 
        
    '''
    h=np.array(h)
    if h.any():
        # h is provided as a 1D array
        if len(h.shape)==1:
            d_arr = np.copy(arr)
            reshape_shape=np.append([arr.shape[0]-2],[1 for i in range(0,arr.ndim -1)]) 
            d_arr[0,...] = (arr[1,...]-arr[0,...])/(h[1]-h[0])
            d_arr[-1,...] = (arr[-1,...]-arr[-2,...])/(h[-1]-h[-2])
            d_arr[1:-1,...] = (arr[2:,...]-arr[0:-2,...])/(np.reshape(h[2:]-h[0:-2],reshape_shape))
         
        #h has the same dimension as var    
        elif h.shape==arr.shape:
            d_arr = np.copy(arr)
            d_arr[0,...] = (arr[1,...]-arr[0,...])/(h[1,...]-h[0,...])
            d_arr[-1,...] = (arr[-1,...]-arr[-2,...])/(h[-1,...]-h[-2,...])
            d_arr[1:-1,...] = (arr[2:,...]-arr[0:-2,...])/(h[2:,...]-h[0:-2,...])
        else:     
            print('Error,h.shape=', h.shape,'arr.shape=',arr.shape)
        
    # h is not defined, we return only d_var, not d_var/dh
    else:
        d_arr = np.copy(arr)
        reshape_shape=np.append([arr.shape[0]-2],[1 for i in range(0,arr.ndim -1)]) 
        d_arr[0,...] = arr[1,...]-arr[0,...]
        d_arr[-1,...] = arr[-1,...]-arr[-2,...]
        d_arr[1:-1,...] = arr[2:,...]-arr[0:-2,...]
        
    
    return d_arr


#========================================================================= 
#=======================vertical grid utilities===========================
#=========================================================================

def gauss_profile(x, alpha,x0=0.):
    """ Return Gaussian line shape at x This can be used to generate a bell-shaped mountain"""
    return np.sqrt(np.log(2) / np.pi) / alpha\
                             * np.exp(-((x-x0) / alpha)**2 * np.log(2))

def compute_uneven_sigma(num_levels, N_scale_heights, surf_res, exponent, zero_top ):
    """
    Construct an initial array of sigma based on the number of levels, an exponent
    Args:
        num_levels: the number of levels
        N_scale_heights: the number of scale heights to the top of the model (e.g scale_heights =12.5 ~102km assuming 8km scale height)
        surf_res: the resolution at the surface
        exponent: an exponent to increase th thickness of the levels
        zero_top: if True, force the top pressure boundary (in N=0) to 0 Pa
    Returns:
        b: an array of sigma layers

    """
    b=np.zeros(int(num_levels)+1)
    for k in range(0,num_levels):
        zeta = 1.-k/np.float(num_levels) #zeta decreases with k
        z  = surf_res*zeta + (1.0 - surf_res)*(zeta**exponent)
        b[k] = np.exp(-z*N_scale_heights)
    b[-1] = 1.0
    if(zero_top):  b[0] = 0.0
    return b


def transition( pfull, p_sigma=0.1, p_press=0.05):
    """
    Return the transition factor to construct the ak and bk 
    Args:
        pfull: the pressure in Pa
        p_sigma: the pressure level where the vertical grid starts transitioning from sigma to pressure
        p_press: the pressure level above those  the vertical grid is pure (constant) pressure
    Returns:
        t: the transition factor =1 for pure sigma, 0 for pure pressure and 0<t<1 for the transition
        
    NOTE:
    In the FV code full pressure are computed from:
                       del(phalf)
         pfull = -----------------------------
                 log(phalf(k+1/2)/phalf(k-1/2))
    """
    t=np.zeros_like(pfull)
    for k in range(0,len(pfull)):
        if( pfull[k] <= p_press): 
            t[k] = 0.0
        elif ( pfull[k] >= p_sigma) :
            t[k] = 1.0
        else:
            x  = pfull[k]    - p_press
            xx = p_sigma - p_press
            t[k] = (np.sin(0.5*np.pi*x/xx))**2
    
    return t

   
def swinbank(plev, psfc, ptrans=1.):
    """
    Compute ak and bk values with a transition based on Swinbank 
    Args:
        plev: the pressure levels in Pa
        psfc: the surface pressure in Pa
        ptrans:the transition pressure in Pa
    Returns:
         aknew, bknew,ks: the coefficients for the new layers
    """

    ktrans= np.argmin(np.abs( plev- ptrans) ) # ks= number of pure pressure levels
    km= len(plev)-1
    
    aknew=np.zeros(len(plev))
    bknew=np.zeros(len(plev))
    
    #   pnorm= 1.e5; 
    pnorm= psfc 
    eta= plev / pnorm
    
    ep= eta[ktrans+1]       #  ks= number of pure pressure levels
    es= eta[-1]
    rnorm= 1. / (es-ep)**2
    
    #   Compute alpha, beta, and gamma using Swinbank's formula
    alpha = (ep**2 - 2.*ep*es) / (es-ep)**2
    beta  =        2.*ep*es**2 / (es-ep)**2
    gamma =        -(ep*es)**2 / (es-ep)**2
    
    #   Pure Pressure levels 
    aknew= eta * pnorm
    
    #  Hybrid pressure-sigma levels
    kdex= range(ktrans+1,km) 
    aknew[kdex] = alpha*eta[kdex] + beta + gamma/eta[kdex] 
    aknew[kdex]= aknew[kdex] * pnorm
    aknew[-1]= 0.0
    
    bknew[kdex] = (plev[kdex] - aknew[kdex])/psfc 
    bknew[-1] = 1.0 
    
    #find the transition level ks where (bk[ks]>0)
    ks=0
    while bknew[ks]==0. :
        ks+=1
    #ks is the one that would be use in fortran indexing in fv_eta.f90    
    return  aknew, bknew,ks
   


def polar_warming(T,lat,outside_range=np.NaN):
    """
    Return the polar warming, following  [McDunn et al. 2013]: Characterization of middle-atmosphere polar warming at Mars, JGR
    A. Kling
    Args:
        T:   temperature array, 1D, 2D or ND, with the latitude dimension FIRST (transpose as needed)
        lat: latitude array
        outside_range: values to set the polar warming to outside the range. Default is Nan but 'zero' may be desirable.
    Returns:
        DT_PW:   The polar warming in [K]
 

    *NOTE*  polar_warming() concatenates the results from both hemispheres obtained from the nested function PW_half_hemisphere()
    """
    
    def PW_half_hemisphere(T_half,lat_half,outside_range=np.NaN):

        #Easy case, T is a 1D on the latitude direction only
        if len(T_half.shape)==1:
            imin=np.argmin(T_half)
            imax=np.argmax(T_half)
            
            #Note that we compute polar warming at ALL latitudes and then set NaN the latitudes outside the desired range. 
            #We test on the absolute values (np.abs) of the latitudes, therefore the function is usable on both hemispheres
            DT_PW_half=T_half-T_half[imin] 
            exclude=np.append(np.where(np.abs(lat_half)-np.abs(lat_half[imin])<0),np.where(np.abs(lat_half[imax])-np.abs(lat_half)<0))
            DT_PW_half[exclude]=outside_range #set to NaN
            return DT_PW_half
        
        #General case for N dimensions        
        else:
            
            #Flatten the diemnsions but the first dimension (the latitudes)
            arr_flat=T_half.reshape([T_half.shape[0], np.prod(T_half.shape[1:])])
            LAT_HALF=np.repeat(lat_half[:,np.newaxis],arr_flat.shape[1],axis=1)
            
            imin=np.argmin(arr_flat,axis=0)
            imax=np.argmax(arr_flat,axis=0)
            
            #Initialize four working arrays
            tmin0,tmax0,latmin0,latmax0=[np.zeros_like(arr_flat) for _ in range(4)]
            
            #get the min/max temperature and latitudes
            for i in range(0,arr_flat.shape[1]):
                tmax0[:,i]=arr_flat[imax[i],i]
                tmin0[:,i]=arr_flat[imin[i],i]
                latmin0[:,i]=lat_half[imin[i]]
                latmax0[:,i]=lat_half[imax[i]]
            
            #Compute polar warming for that hemisphere
            DT_PW_half=arr_flat-tmin0
            
            # Set to NaN values outside the range. 
            tuple_lower_than_latmin=np.where(np.abs(LAT_HALF)-np.abs(latmin0)<0)
            tuple_larger_than_latmax=np.where(np.abs(latmax0)-np.abs(LAT_HALF)<0)
            
            DT_PW_half[tuple_lower_than_latmin]=outside_range
            DT_PW_half[tuple_larger_than_latmax]=outside_range
        
            return DT_PW_half.reshape(T_half.shape)

    #======================================================
    #======Actual calculations for both hemispheres========
    #======================================================
    T_SH=T[0:len(lat)//2]
    lat_SH=lat[0:len(lat)//2]
    
    T_NH=T[len(lat)//2:]
    lat_NH=lat[len(lat)//2:]

    return np.concatenate((PW_half_hemisphere(T_SH,lat_SH,outside_range),PW_half_hemisphere(T_NH,lat_NH,outside_range)),axis=0) 


def tshift(array, lon=None, timex=None, nsteps_out=None):
    '''
    Conversion to uniform local time, original implementation from Richard (Minor modification to the DEFAULT object by Alex)
    
    
    Interpolate onto a new time grid with nsteps_out samples per sol  
    New time:   [ 0 ... nn-1/nsteps_out ]*24 
    Args:
        array: variable to be shifted. Assume longitude is the first dimension and time in the last dimension
        lon: longitude
        timex should be in units of hours  (only timex(1) is actually relevant)
        nsteps_out
    Returns:
        tshift: array shifted to uniform local time.

    '''
    if np.shape(array) == len(array):
        print('Need longitude and time dimensions')
        return
          
    dims=np.shape(array)  #get dimensions of array
    end=len(dims)-1
    id=dims[0]   #number of longitudes in file
    if lon is None:
        lon = np.linspace(0.,360.,num=id,endpoint=False)
    if timex is None:
        nsteps=dims[end]
        timex = np.linspace(0.,24.,num=nsteps,endpoint=False)
    else:
        nsteps=len(timex)


    nsf = np.float_(nsteps)

    timex = np.squeeze(timex)

    if timex.max() <= 1.:   #if timex is in fractions of day
        timex = 24.*timex
        
    if nsteps_out is None:
        nsteps_out = nsteps

    #Assuming time is last dimension, check if it is local time timex
    #If not, reshape the array into (stuff, days, local time)
    if dims[end] != nsteps:
        ndays = dims[end] / nsteps
        if ndays*nsteps != dims[end]:
            print('Time dimensions do not conform')
            return
        array = np.reshape(array,(dims[0,end-1], nsteps, ndays))
        newdims=np.linspace(len(dims+1),dtype=np.int32)
        newdims[len(dims)-1]=len(dims)
        newdims[len(dims)]=len(dims)-1
        array = np.transpose(array,newdims)
    
    dims=np.shape(array) #get new dims of array if reshaped

    
    if len(dims) > 2:
        recl = np.prod(dims[1:len(dims)-1])
    else:
        recl=1
            

    array=np.reshape(array,(id,recl,nsteps))
    #create output array
    narray=np.zeros((id,recl,nsteps_out))
    
    dt_samp = 24.0/nsteps      #   Time increment of input data (in hours)
    dt_save = 24.0/nsteps_out  #   Time increment of output data (in hours)
    
    #             calculate interpolation indices
    # convert east longitude to equivalent hours 
    xshif = 24.0*lon/360.
    kk=np.where(xshif < 0)
    xshif[kk]=xshif[kk]+24.

    fraction = np.zeros((id,nsteps_out))
    imm = np.zeros((id,nsteps_out))
    ipp = np.zeros((id,nsteps_out))

    for nd in range(nsteps_out):
        dtt = nd*dt_save - xshif - timex[0] + dt_samp
        #      insure that data local time is bounded by [0,24] hours
        kk = np.where(dtt < 0.)
        dtt[kk] = dtt[kk] + 24.
        
        im = np.floor(dtt/dt_samp)    #  this is index into the data aray
        fraction[:,nd] = dtt-im*dt_samp
        kk = np.where(im < 0.)
        im[kk] = im[kk] + nsf
        
        ipa = im + 1.
        kk = np.where(ipa >= nsf)
        ipa[kk] = ipa[kk] - nsf
        
        imm[:,nd] = im[:]
        ipp[:,nd] = ipa[:]

    fraction = fraction / dt_samp # assume uniform tinc between input data samples
    
    #           Now carry out the interpolation
    for nd in range(nsteps_out):    #   Number of output time levels
        for i in range(id):         #   Number of longitudes
            im = np.int(imm[i,nd])%24
            ipa= np.int(ipp[i,nd])
            frac = fraction[i,nd]
            narray[i,:,nd] = (1.-frac)*array[i,:,im] + frac*array[i,:,ipa]

    narray = np.squeeze(narray)
    ndimsfinal=np.zeros(len(dims),dtype=int)
    for nd in range(end):
        ndimsfinal[nd]=dims[nd]
    ndimsfinal[end]=nsteps_out
    narray = np.reshape(narray,ndimsfinal)

    return narray