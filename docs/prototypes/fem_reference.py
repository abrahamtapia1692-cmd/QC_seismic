"""Experimento previo: Rayleigh con discretización vertical independiente."""
import numpy as np
from scipy.linalg import eigh


def phase(k, layers, dz, depth):
    z = [0.]
    bottom = 0.
    properties = []
    for h, vp, vs, rho in layers:
        stop = bottom + h if h else depth
        count = max(1, int(np.ceil((stop-bottom)/dz)))
        for b in np.linspace(bottom,stop,count+1)[1:]:
            z.append(b)
            properties.append((vp,vs,rho))
        bottom = stop
    n = len(z)
    K = np.zeros((2*n,2*n)); M = K.copy()
    for j, (vp,vs,rho) in enumerate(properties):
        h = z[j+1]-z[j]
        mu = rho*vs**2; lam = rho*(vp**2-2*vs**2)
        H = h*np.array([[2.,1.],[1.,2.]])/6
        G = np.array([[1.,-1.],[-1.,1.]])/h
        B = np.array([[-.5,.5],[-.5,.5]])
        local = np.block([[(lam+2*mu)*k*k*H+mu*G,k*(lam*B-mu*B.T)],
                          [k*(lam*B.T-mu*B),(lam+2*mu)*G+mu*k*k*H]])
        mass = np.block([[rho*H,np.zeros((2,2))],[np.zeros((2,2)),rho*H]])
        ix = [2*j,2*j+2,2*j+1,2*j+3]
        K[np.ix_(ix,ix)] += local
        M[np.ix_(ix,ix)] += mass
    eig = eigh(K[:-2,:-2], M[:-2,:-2], subset_by_index=(0,0), check_finite=False, eigvals_only=True)
    return np.sqrt(eig[0])/k


if __name__ == "__main__":
    for dx in (2.,1.,.5):
        print(dx, phase(.1,[(0.,400.,200.,1800.)],dx,200.))
