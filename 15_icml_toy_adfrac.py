import cvxopt as co
import numpy as np
import pylab as pl
import sklearn.metrics as metric
import matplotlib.pyplot as plt
import scipy.io as io

from kernel import Kernel
from ocsvm import OCSVM
from latent_ocsvm import LatentOCSVM

from toydata import ToyData
from so_hmm import SOHMM


def get_model(num_exm, num_train, lens, block_len, blocks=1, anomaly_prob=0.15):
    print('Generating {0} sequences, {1} for training, each with {2} anomaly probability.'.format(num_exm, num_train, anomaly_prob))
    cnt = 0 
    X = [] 
    Y = []
    label = []
    lblcnt = co.matrix(0.0,(1,lens))
    for i in range(num_exm):
        (exm, lbl, marker) = ToyData.get_2state_anom_seq(lens, block_len, anom_prob=anomaly_prob, num_blocks=blocks)
        cnt += lens
        X.append(exm)
        Y.append(lbl)
        label.append(marker)
        # some lbl statistics
        if i<num_train:
            lblcnt += lbl
    X = normalize_sequence_data(X, num_train)
    return (SOHMM(X[0:num_train],Y[0:num_train]), SOHMM(X[num_train:],Y[num_train:]), SOHMM(X,Y), label)


def normalize_sequence_data(X, num_train, dims=1):
    cnt = 0
    tst_mean = co.matrix(0.0, (1, dims))
    for i in range(num_train):
        lens = len(X[i][0, :])
        cnt += lens
        tst_mean += co.matrix(1.0, (1, lens)) * X[i].trans()
    tst_mean /= float(cnt)
    print tst_mean

    max_val = co.matrix(-1e10, (1, dims))
    for i in range(len(X)):
        for d in range(dims):
            X[i][d, :] = X[i][d, :] - tst_mean[d]
            foo = np.max(np.abs(X[i][d, :]))
            if i < num_train:
                max_val[d] = np.max([max_val[d], foo])

    print max_val
    for i in range(len(X)):
        for d in range(dims):
            X[i][d, :] /= max_val[d]

    cnt = 0
    max_val = co.matrix(-1e10, (1, dims))
    tst_mean = co.matrix(0.0, (1, dims))
    for i in range(len(X)):
        lens = len(X[i][0, :])
        cnt += lens
        tst_mean += co.matrix(1.0, (1, lens)) * X[i].trans()
        for d in range(dims):
            foo = np.max(np.abs(X[i][d, :]))
            max_val[d] = np.max([max_val[d], foo])
    print tst_mean / float(cnt)
    print max_val
    return X


def build_histograms(data, phi, num_train, bins=2, ord=2):
    # first num_train phis are used for estimating
    # histogram boundaries.
    N = len(data)
    (F, LEN) = data[0].size

    max_phi = np.max(phi[:,:num_train])
    min_phi = np.min(phi[:,:num_train])
    print("Build histograms with {0} bins.".format(bins))
    print (max_phi, min_phi)
    thres = np.linspace(min_phi, max_phi+1e-8, bins+1)
    print (max_phi, min_phi)

    hist = co.matrix(0.0, (F*bins, 1))
    phi_hist = co.matrix(0.0, (F*bins, N))
    for i in xrange(N):
        for f in xrange(F):
            phi_hist[0 + f*bins,i] = np.where(np.array(data[i][f,:])<thres[0])[0].size
            for b in range(1,bins-1):
                cnt = np.where((np.array(data[i][f,:])>=thres[b]) & (np.array(data[i][f,:])<thres[b+1]))[0].size
                phi_hist[b + f*bins,i] = float(cnt)
            phi_hist[bins-1 + f*bins,i] = np.where(np.array(data[i][f,:])>=thres[bins-1])[0].size
        phi_hist[:,i] /= np.linalg.norm(phi_hist[:,i], ord=ord)
        hist += phi_hist[:,i]/float(N)
    print('Histogram:')
    print hist.trans()
    kern = Kernel.get_kernel(phi_hist, phi_hist)
    return kern, phi_hist


def build_seq_kernel(data, ord=2, type='linear', param=1.0):
    # all sequences have the same length
    N = len(data)
    (F, LEN) = data[0].size
    phi = co.matrix(0.0, (F*LEN, N))
    for i in xrange(N):
        for f in xrange(F):
            phi[(f*LEN):(f*LEN)+LEN,i] = data[i][f,:].trans()
        if ord>=1:
            phi[:,i] /= np.linalg.norm(phi[:,i], ord=ord)
    kern = Kernel.get_kernel(phi, phi, type=type, param=param)
    return kern, phi


def build_fisher_kernel(data, labels, num_train, ord=2, param=2, set_rand=False):
    # estimate the transition and emission matrix given the training
    # data only. Number of states is specifified in 'param'.
    N = len(data)
    (F, LEN) = data[0].size

    A = np.zeros((param, param))
    E = np.zeros((param, F))

    phi = co.matrix(0.0, (param * param + F * param, N))
    cnt = 0
    cnt_states = np.zeros(param)
    for n in xrange(num_train):
        lbl = np.array(labels[n])[0, :]
        exm = np.array(data[n])
        for i in range(param):
            for j in range(param):
                A[i, j] += np.where((lbl[:-1] == i) & (lbl[1:] == j))[0].size
        for i in range(param):
            for f in range(F):
                inds = np.where(lbl == i)[0]
                E[i, f] += np.sum(exm[f, inds])
                cnt_states[i] += inds.size
        cnt += LEN

    for i in range(param):
        E[i, :] /= cnt_states[i]
    sol = co.matrix(np.vstack((A.reshape(param * param, 1) / float(cnt), E.reshape(param * F, 1))))
    print sol

    if set_rand:
        print('Set random parameter vector for Fisher kernel.')
        # sol = co.uniform(param*param+param*F, a=-1.0, b=+1.0)
        sol = co.uniform(param * param + param * F)

    model = SOHMM(data, labels)
    for n in range(N):
        (val, latent, phi[:, n]) = model.argmax(sol, n)
        phi[:, n] /= np.linalg.norm(phi[:, n], ord=ord)

    kern = Kernel.get_kernel(phi, phi)
    return kern, phi


def build_kernel(data, labels, num_train, bins=2, ord=2, typ='linear', param=1.0):
    if typ == 'hist':
        foo, phi = build_seq_kernel(data, ord=-1)
        return build_histograms(data, phi, num_train, bins=param, ord=ord)
    elif typ == 'fisher':
        return build_fisher_kernel(data, labels, num_train, ord=ord, param=param, set_rand=False)
    elif typ == 'fisher-rand':
        return build_fisher_kernel(data, labels, num_train, ord=ord, param=param, set_rand=True)
    else:
        return build_seq_kernel(data, ord=ord, type=typ.lower(), param=param)


def test_bayes(phi, kern, train, test, num_train, anom_prob, labels):
    # bayes classifier
    (DIMS, N) = phi.size
    w_bayes = co.matrix(-1.0, (DIMS, 1))
    pred = w_bayes.trans()*phi[:,num_train:]
    (fpr, tpr, thres) = metric.roc_curve(labels[num_train:], pred.trans())
    auc = metric.auc(fpr, tpr)
    return auc


def test_ocsvm(phi, kern, train, test, num_train, anom_prob, labels):
    auc = 0.5
    ocsvm = OCSVM(kern[:num_train,:num_train], C=1.0/(num_train*anom_prob))
    msg = ocsvm.train_dual()
    if not msg==OCSVM.MSG_ERROR:
        (oc_as, foo) = ocsvm.apply_dual(kern[num_train:,ocsvm.get_support_dual()])
        (fpr, tpr, thres) = metric.roc_curve(labels[num_train:], oc_as)
        auc = metric.auc(fpr, tpr)
    return auc


def test_hmad(phi, kern, train, test, num_train, anom_prob, labels, zero_shot=False):
    auc = 0.5
    # train structured anomaly detection
    sad = LatentOCSVM(train, C=1.0/(num_train*anom_prob))
    (lsol, lats, thres) = sad.train_dc(max_iter=60, zero_shot=zero_shot)
    (pred_vals, pred_lats) = sad.apply(test)    
    (fpr, tpr, thres) = metric.roc_curve(labels[num_train:], pred_vals)
    auc = metric.auc(fpr, tpr)
    return auc


if __name__ == '__main__':
    LENS = 600
    EXMS = 800
    EXMS_TRAIN = 400
    REPS = 50
    BLOCK_LEN = 120

    LVL = [0.025, 0.05, 0.1, 0.15, 0.2, 0.3]
    BLOCKS = 2

    # methods = ['Bayes' ,'HMAD','OcSvm','OcSvm','OcSvm','OcSvm','OcSvm','OcSvm','OcSvm','OcSvm']
    # kernels = ['Linear',''    ,'RBF'  ,'RBF'  ,'RBF'  ,'Hist' ,'Hist' ,'Hist' ,'Linear','Linear']
    # kparams = [''      ,''    ,  00.1 ,  01.0 ,  10.0 , 4     , 8     , 10    , ''     , '']
    # ords    = [+1      , 1    ,  1    ,  1    ,  1    , 1     , 1     , 1     , 1      , 2]

    #methods = ['OcSvm','OcSvm','OcSvm']
    #kernels = ['RBF'  ,'RBF'  ,'RBF'  ]
    #kparams = [  10.1 ,  100.0  ,  1000.0  ]
    #ords    = [  1    ,  1    ,  1    ]

    methods = ['Bayes', 'HMAD', 'OcSvm', 'OcSvm']
    kernels = ['Linear', '', 'Fisher', 'Fisher-Rand']
    kparams = [1, '', 2, 2]
    ords    = [1, 1, 1, 1]

    # collected means
    res = []
    for r in xrange(REPS):
        for b in xrange(len(LVL)):
            (train, test, comb, labels) = get_model(EXMS, EXMS_TRAIN, LENS, BLOCK_LEN, blocks=BLOCKS, anomaly_prob=LVL[b])
            for m in range(len(methods)):
                name = 'test_{0}'.format(methods[m].lower())
                (kern, phi) = build_kernel(comb.X, comb.y, EXMS_TRAIN, ord=ords[m], typ=kernels[m].lower(), param=kparams[m])
                print('Calling {0}'.format(name))
                auc = eval(name)(phi, kern, train, test, EXMS_TRAIN, LVL[b], labels)
                print('-------------------------------------------------------------------------------')
                print 
                print('Iter {0}/{1} in lvl {2}/{3} for method {4} ({5}/{6}) got AUC = {7}.'.format(r+1,REPS,b+1,len(LVL),name,m+1,len(methods),auc))
                print
                print('-------------------------------------------------------------------------------')

                if len(res)<=b:
                    res.append([])
                mlist = res[b]
                if len(mlist)<=m:
                    mlist.append([])
                cur = mlist[m]
                cur.append(auc)

    print('RESULTS >-----------------------------------------')
    print 
    aucs = np.ones((len(methods),len(LVL)))
    stds = np.ones((len(methods),len(LVL)))
    varis = np.ones((len(methods),len(LVL)))
    names = []

    for b in range(len(LVL)):
        print("LVL={0}:".format(LVL[b]))
        for m in range(len(methods)):
            auc = np.mean(res[b][m])
            std = np.std(res[b][m])
            var = np.var(res[b][m])
            aucs[m,b] = auc
            stds[m,b] = std
            varis[m,b] = var
            kname = '' 
            if kernels[m]=='RBF' or kernels[m]=='Hist':
                kname = ' ({0} {1})'.format(kernels[m],kparams[m])
            elif kernels[m]=='Linear':
                kname = ' ({0})'.format(kernels[m])
            name = '{0}{1} [{2}]'.format(methods[m],kname,ords[m])
            if len(names)<=m:
                names.append(name)
            print("   m={0}: AUC={1} STD={2} VAR={3}".format(name,auc,std,var))
        print


    print aucs
    # store result as a file
    data = {}
    data['LENS'] = LENS
    data['EXMS'] = EXMS
    data['EXMS_TRAIN'] = EXMS_TRAIN
    data['ANOM_PROB'] = LVL
    data['REPS'] = REPS
    data['BLOCKS'] = BLOCKS
    data['LVL'] = LVL

    data['methods'] = methods
    data['kernels'] = kernels
    data['kparams'] = kparams
    data['ords'] = ords

    data['res'] = res
    data['aucs'] = aucs
    data['stds'] = stds
    data['varis'] = varis
    data['names'] = names

    io.savemat('15_icml_toy_adfrac_c0.mat', data)

    print('finished')
