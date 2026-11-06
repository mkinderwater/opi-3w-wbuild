#!/usr/bin/env python3
from pathlib import Path
import numpy as np,sys,json,hashlib
import cv2
import argparse
parser=argparse.ArgumentParser(description='Reproduce LeNet CPU references with OpenCV and independent NumPy layers.')
parser.add_argument('--sdk',required=True);parser.add_argument('--output',required=True);args=parser.parse_args()
p=Path(args.sdk)
def varint(b,o):
 v=0;s=0
 while True:
  x=b[o];o+=1;v|=(x&127)<<s
  if x<128:return v,o
  s+=7

def fields(b):
 o=0
 while o<len(b):
  k,o=varint(b,o);kind=k&7;n=k>>3
  if kind==2:size,o=varint(b,o);v=b[o:o+size];o+=size
  elif kind==0:v,o=varint(b,o)
  elif kind==5:v=b[o:o+4];o+=4
  elif kind==1:v=b[o:o+8];o+=8
  else:raise ValueError(kind)
  yield n,kind,v
weights={}
for n,k,v in fields((p/'models/lenet/lenet.caffemodel').read_bytes()):
 if n!=100:continue
 f=list(fields(v));name=next((x.decode() for a,b,x in f if a==1),'')
 blobs=[]
 for a,b,x in f:
  if a!=7:continue
  bf=list(fields(x));data=b''.join(v for n,k,v in bf if n==5)
  blobs.append(np.frombuffer(data,dtype='<f4'))
 if blobs:weights[name]=blobs
print({k:[x.size for x in v] for k,v in weights.items()})
def conv(x,w,b,out):
 w=w.reshape(out,x.shape[1],5,5)
 windows=np.lib.stride_tricks.sliding_window_view(x,(5,5),axis=(2,3))
 return np.einsum('nchwkl,ockl->nohw',windows,w,optimize=True)+b.reshape(1,-1,1,1)
def pool(x):
 n,c,h,w=x.shape;return x.reshape(n,c,h//2,2,w//2,2).max(axis=(3,5))
def cpu(x):
 y=pool(conv(x,*weights['conv1'],20));y=pool(conv(y,*weights['conv2'],50))
 y=np.maximum(y.reshape(1,-1)@weights['ip1'][0].reshape(500,-1).T+weights['ip1'][1],0)
 y=y@weights['ip2'][0].reshape(10,-1).T+weights['ip2'][1];y=np.exp(y-y.max());return (y/y.sum()).ravel()
x7=np.zeros((28,28),dtype=np.uint8);x7[6:9,6:22]=255
for y in range(8,24):
 x=21-round((y-8)*12/16);x7[y,x-1:x+2]=255
cases=[('sdk-zero',(p/'examples/lenet/input_data/lenet.dat').read_bytes()),('synthetic-seven',x7.tobytes())]
net=cv2.dnn.readNetFromCaffe(str(p/'models/lenet/lenet.prototxt'),str(p/'models/lenet/lenet.caffemodel'))
refs=[]
for name,data in cases:
 x=np.frombuffer(data,dtype=np.uint8).reshape(1,1,28,28).astype(np.float32)/255
 net.setInput(x);a=net.forward().ravel();b=cpu(x);assert np.allclose(a,b,atol=1e-5),(a,b)
 print(name,'class',int(a.argmax()),'scores',a.tolist(),'reference error',float(np.max(abs(a-b))))
 refs.append(dict(name=name,input_sha256=hashlib.sha256(data).hexdigest(),scores=a.tolist(),class_index=int(a.argmax()),reference_agreement_max_abs_error=float(np.max(abs(a-b)))))
Path(args.output).write_text(json.dumps(dict(schema=1,model='SDK LeNet v3 / A733',input_normalization='uint8 / 255',reference_engines=['OpenCV 4.10.0 CPU DNN','independent NumPy implementation of Caffe LeNet layers'],source_weights_sha256=hashlib.sha256((p/'models/lenet/lenet.caffemodel').read_bytes()).hexdigest(),source_prototxt_sha256=hashlib.sha256((p/'models/lenet/lenet.prototxt').read_bytes()).hexdigest(),absolute_tolerance=0.03,cases=refs),indent=2)+'\n')
