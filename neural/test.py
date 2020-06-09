import torch
import torch.nn as nn
from torch.nn.init import xavier_normal
import argparse
from torch.utils.data.dataset import TensorDataset
from torch.utils.data import DataLoader
import torch.nn.functional as F
from torch import optim
from torch.autograd import Variable
from sklearn.metrics import average_precision_score,f1_score,precision_score,recall_score
from torch.nn.modules.loss import BCELoss
import numpy as np
from tqdm import tqdm
torch.manual_seed(0)
np.random.seed(0)
def read_args() : 

	parser = argparse.ArgumentParser(description='Train Fact prediction with PyTorch.')
	parser.add_argument('--dataset', action='store', type=str, dest='dataset',
						help='Path to dataset')
	parser.add_argument('--embed', action='store', type=int, dest='embed_size', default=100,help='embedding size (note for complex it is 2*value, default 100')
	parser.add_argument('--batch-size', action='store', type=int, dest='batch_size', default=100,help='batch size - default 100')
	parser.add_argument('--epochs', action='store', type=int, dest='epochs', default=50,help='num of epochs default 50')
	parser.add_argument('--cuda', action='store', type=int, dest='use_cuda', default=0,help='cuda device id to use, by default 0 (-1 for CPU training)')
	parser.add_argument('--neg-samples', action='store', type=int, dest='neg_samples', default=1,help='Negative samples per positive sample, 1 for each head and tail')
	parser.add_argument('--lr', action='store', type=float, dest='lr', default=0.01,help='Fixed learning rate')
	parser.add_argument('--model', action='store', type=str, dest='model', default='ComplEx',help='model to use (ComplEx/ConvE)')
	parser.add_argument('--save',action='store',type=str,dest='save_model',default='model.pt',help='Saved model file name. The model stored is the one with best score on validation set')
	parser.add_argument('--file',action='store',type=str,dest='file',default='',help='Predictions file name. The model stores prediction on test set')
	return parser.parse_args()


args = read_args()

use_cuda = False
if args.use_cuda!=-1:
	use_cuda=True
	torch.cuda.manual_seed(0)
	torch.cuda.set_device(args.use_cuda)
# read dataset from folder 'dataset'

train_features = []
test_features = []
test_labels = []
valid_features = []
valid_labels = []

# build vocab as well

entity_to_id = {}
id_to_entity = []

relation_to_id = {}
id_to_relation = []

knowns_o={}
knowns_s = {} 

for line in open(args.dataset+'/train.txt'):
	a,b,c = line.rstrip().split()
	for i in (a,c):
		if i not in entity_to_id:
			entity_to_id[i]=len(id_to_entity)
			id_to_entity.append(i)
	if b not in relation_to_id :
		relation_to_id[b]=len(id_to_relation)
		id_to_relation.append(b)
	train_features.append([entity_to_id[a],relation_to_id[b],entity_to_id[c]])
	if (entity_to_id[a], relation_to_id[b]) not in knowns_o:
		knowns_o[(entity_to_id[a], relation_to_id[b])] = set()
	knowns_o[(entity_to_id[a], relation_to_id[b])].add(entity_to_id[c]) 
	if (entity_to_id[c], relation_to_id[b]) not in knowns_s:
		knowns_s[(entity_to_id[c], relation_to_id[b])] = set()
	knowns_s[(entity_to_id[c], relation_to_id[b])].add(entity_to_id[a]) 

for line in open(args.dataset+'/valid.txt'):
	a,b,c,d = line.rstrip().split()
	d = int(d)
	for i in (a,c):
		if i not in entity_to_id:
			entity_to_id[i]=len(id_to_entity)
			id_to_entity.append(i)
	if b not in relation_to_id :
		relation_to_id[b]=len(id_to_relation)
		id_to_relation.append(b)
	valid_features.append([entity_to_id[a],relation_to_id[b],entity_to_id[c]])
	valid_labels.append(d)
	if (entity_to_id[a], relation_to_id[b]) not in knowns_o:
		knowns_o[(entity_to_id[a], relation_to_id[b])] = set()
	knowns_o[(entity_to_id[a], relation_to_id[b])].add(entity_to_id[c])
	if (entity_to_id[c], relation_to_id[b]) not in knowns_s:
		knowns_s[(entity_to_id[c], relation_to_id[b])] = set()
	knowns_s[(entity_to_id[c], relation_to_id[b])].add(entity_to_id[a])  

for line in open(args.dataset+'/test.txt'):
	a,b,c,d = line.rstrip().split()
	d = int(d)
	for i in (a,c):
		if i not in entity_to_id:
			entity_to_id[i]=len(id_to_entity)
			id_to_entity.append(i)
	if b not in relation_to_id :
		relation_to_id[b]=len(id_to_relation)
		id_to_relation.append(b)
	test_features.append([entity_to_id[a],relation_to_id[b],entity_to_id[c]])
	test_labels.append(d)
	if (entity_to_id[a], relation_to_id[b]) not in knowns_o:
		knowns_o[(entity_to_id[a], relation_to_id[b])] = set()
	knowns_o[(entity_to_id[a], relation_to_id[b])].add(entity_to_id[c]) 
	if (entity_to_id[c], relation_to_id[b]) not in knowns_s:
		knowns_s[(entity_to_id[c], relation_to_id[b])] = set()
	knowns_s[(entity_to_id[c], relation_to_id[b])].add(entity_to_id[a]) 

for k in knowns_o:
	knowns_o[k] = list(knowns_o[k])
for k in knowns_s:
	knowns_s[k] = list(knowns_s[k])
# print(knowns_o)
# exit()

def get_knowns(e, r, flag_s_o=0):
		"""
		computes and returns the set of all entites that have been seen as a fact (s, r, _) or (_, r, o)\n
		:param e: The head(s)/tail(o) of the fact
		:param r: The relation of the fact
		:param flag_s_o: whether e is s #s is fixed we try o
		:return: All entites o such that (s, r, o) has been seen in all_kb 
				 OR
				 All entites s such that (s, r, o) has been seen in all_kb 
		"""
		if flag_s_o:
			ks = [knowns_o[(a, b)] for a,b in zip(e, r)]
		else:
			ks = [knowns_s[(a, b)] for a,b in zip(e, r)]
		lens = [len(x) for x in ks]
		max_lens = max(lens)
		ks = [np.pad(x, (0, max_lens-len(x)), 'edge') for x in ks]
		result= np.array(ks)
		return result

org_test_indices = []
# if dataset had a original test set
try : 
	f = open(args.dataset+'/org_test.txt','r')
	temp_facts = set([tuple(i.rstrip().split()) for i in f])
	for i,line in enumerate(open(args.dataset+'/test.txt')):
		test_fact = line.rstrip().split()[:-1]
		if tuple(test_fact) in temp_facts:
			org_test_indices.append(i)
	print('num org test indices',len(org_test_indices))
except:
	pass
print('Entity vocab size',len(entity_to_id))
print('relation vocab size',len(relation_to_id))

print('Train size',len(train_features))
print('Valid size',len(valid_features))
print('test size',len(test_features))

import sys
sys.stdout.flush()

valid_features = torch.LongTensor(valid_features)
valid_labels = torch.LongTensor(valid_labels)
test_features = torch.LongTensor(test_features)
test_labels = torch.LongTensor(test_labels)

valid_set = TensorDataset(valid_features,valid_labels)
test_set = TensorDataset(test_features,test_labels)

valid_loader = DataLoader(valid_set,batch_size=args.batch_size,shuffle=False)
test_loader = DataLoader(test_set,batch_size=args.batch_size,shuffle=False)

def get_train_loader(train_features,neg_samples=1):
	new_features = []
	new_labels = []
	for i in (range(len(train_features))):
		samples = 0
		s,r,o = train_features[i]
		new_features.append([s,r,o])
		new_labels.append(1)
		while samples<neg_samples:
			n_s = np.random.randint(len(id_to_entity))
			n_o = np.random.randint(len(id_to_entity))
			if n_s==n_o or n_s==s or n_o==o: continue
			new_features.append([n_s,r,o])
			new_labels.append(0)
			new_features.append([s,r,n_o])
			new_labels.append(0)
			samples+=1
	train_set = TensorDataset(torch.LongTensor(new_features),torch.LongTensor(new_labels))
	train_loader = DataLoader(train_set,batch_size=args.batch_size,shuffle=True)
	return train_loader

# define models 

class Complex(torch.nn.Module):
	def __init__(self, num_entities, num_relations,embedding_dim):
		super(Complex, self).__init__()
		self.emb_e_real = torch.nn.Embedding(num_entities, embedding_dim)
		self.emb_e_img = torch.nn.Embedding(num_entities, embedding_dim)
		self.emb_rel_real = torch.nn.Embedding(num_relations, embedding_dim)
		self.emb_rel_img = torch.nn.Embedding(num_relations, embedding_dim)
		xavier_normal(self.emb_e_real.weight.data)
		xavier_normal(self.emb_e_img.weight.data)
		xavier_normal(self.emb_rel_real.weight.data)
		xavier_normal(self.emb_rel_img.weight.data)

	def forward(self, e1, rel, e2):
		e1_embedded_real = self.emb_e_real(e1).unsqueeze(1)
		#print('e1 shape',e1_embedded_real.size())
		rel_embedded_real = self.emb_rel_real(rel).unsqueeze(1)
		#print('rel shape',rel_embedded_real.size())
		e2_embedded_real = self.emb_e_real(e2).unsqueeze(1)
		#print('e2 shape',e2_embedded_real.size())
		e1_embedded_img =  self.emb_e_img(e1).unsqueeze(1)
		rel_embedded_img = self.emb_rel_img(rel).unsqueeze(1)
		e2_embedded_img = self.emb_e_img(e2).unsqueeze(1)
		realrealreal = torch.matmul(e1_embedded_real*rel_embedded_real, e2_embedded_real.transpose(2,1))
		#print('product shape',realrealreal.size())
		realimgimg = torch.matmul(e1_embedded_real*rel_embedded_img, e2_embedded_img.transpose(2,1))
		imgrealimg = torch.matmul(e1_embedded_img*rel_embedded_real, e2_embedded_img.transpose(2,1))
		imgimgreal = torch.matmul(e1_embedded_img*rel_embedded_img, e2_embedded_real.transpose(2,1))
		pred = realrealreal + realimgimg + imgrealimg - imgimgreal
		pred = F.sigmoid(pred.squeeze())
		return pred

	def test(self, e1, rel,e2):
		e1_embedded_real = self.emb_e_real.weight.unsqueeze(0) if e1 is None else self.emb_e_real(e1).unsqueeze(1)
		#print('e1 shape',e1_embedded_real.size())
		rel_embedded_real = self.emb_rel_real(rel).unsqueeze(1)
		#print('rel shape',rel_embedded_real.size())
		e2_embedded_real = self.emb_e_real.weight.unsqueeze(0) if e2 is None else self.emb_e_real(e2).unsqueeze(1)
		#print('e2 shape',e2_embedded_real.size())
		e1_embedded_img =  self.emb_e_img.weight.unsqueeze(0)  if e1 is None else self.emb_e_img(e1).unsqueeze(1)
		rel_embedded_img = self.emb_rel_img(rel).unsqueeze(1)
		e2_embedded_img = self.emb_e_img.weight.unsqueeze(0)  if e2 is None else self.emb_e_img(e2).unsqueeze(1)
		print(e1_embedded_real.shape)
		print(rel_embedded_real.shape)
		print(e2_embedded_real.shape)
		realrealreal = e1_embedded_real*rel_embedded_real*e2_embedded_real
		print('product shape',realrealreal.size())
		realimgimg =e1_embedded_real*rel_embedded_img*e2_embedded_img
		imgrealimg = e1_embedded_img*rel_embedded_real*e2_embedded_img
		imgimgreal = e1_embedded_img*rel_embedded_img*e2_embedded_real
		pred = (realrealreal + realimgimg + imgrealimg - imgimgreal).sum(dim=-1).unsqueeze(1)
		print(pred.shape)
		pred = F.sigmoid(pred.squeeze())
		return pred

# ConvE
class Flatten(nn.Module):
	def forward(self, x):
		n, _, _, _ = x.size()
		x = x.view(n, -1)
		return x


class ConvE(nn.Module):
	def __init__(self, num_e, num_r, embedding_size_h=20, embedding_size_w=10,
				 conv_channels=32, conv_kernel_size=3):
		super().__init__()
		self.num_e = num_e
		self.num_r = num_r
		self.embedding_size_h = embedding_size_h
		self.embedding_size_w = embedding_size_w
		embedding_size = embedding_size_h * embedding_size_w
		flattened_size = (embedding_size_w * 2 - conv_kernel_size + 1) * \
						 (embedding_size_h - conv_kernel_size + 1) * conv_channels
		self.embed_e = nn.Embedding(num_embeddings=self.num_e, embedding_dim=embedding_size)
		self.embed_r = nn.Embedding(num_embeddings=self.num_r, embedding_dim=embedding_size)
		self.conv_e = nn.Sequential(
			nn.Conv2d(in_channels=1, out_channels=conv_channels, kernel_size=conv_kernel_size),
			nn.ReLU(),
			nn.BatchNorm2d(num_features=conv_channels),
			Flatten(),
			nn.Linear(in_features=flattened_size, out_features=embedding_size),
			nn.ReLU(),
			nn.BatchNorm1d(num_features=embedding_size),
		)
	def forward(self, e1, r,e2):
		embed_e1 = self.embed_e(e1)
		embed_r = self.embed_r(r)
		embed_e2 = self.embed_e(e2).unsqueeze(1)
		embed_e = embed_e1.view(-1, self.embedding_size_w, self.embedding_size_h)
		embed_r = embed_r.view(-1, self.embedding_size_w, self.embedding_size_h)
		conv_input = torch.cat([embed_e, embed_r], dim=1).unsqueeze(1)
		out = self.conv_e(conv_input).unsqueeze(1)
		#print('out',out.size())
		scores = F.sigmoid(out.matmul(embed_e2.transpose(2,1)))
		#print('scores')
		return scores.squeeze()

	def test(self, e1, r,e2):
		embed_e1 = self.embed_e(e1)
		embed_r = self.embed_r(r)
		embed_e2 = self.embed_e.weight.unsqueeze(0)
		embed_e = embed_e1.view(-1, self.embedding_size_w, self.embedding_size_h)
		embed_r = embed_r.view(-1, self.embedding_size_w, self.embedding_size_h)
		conv_input = torch.cat([embed_e, embed_r], dim=1).unsqueeze(1)
		out = self.conv_e(conv_input).unsqueeze(1)
		#print('out',out.size())
		scores = F.sigmoid(out.matmul(embed_e2.transpose(2,1)))
		#print('scores')
		return scores.squeeze()


# training 

# evaluation metrics
def evaluate(labels,predictions,features,arg_threshold = None,org_test_indices=set([]),dname=''):
	thresholds = [i/100 for i in range(0,105,5)]
	labels = list(map(int,labels))
	cat_labels = [labels[i] for i in range(len(labels)) if id_to_relation[features[i][1]]=='has_label']
	rel_labels = [labels[i] for i in range(len(labels)) if id_to_relation[features[i][1]]!='has_label']
	best_wf1 =0.0
	best_threshold = 0
	if arg_threshold is None:
		for threshold in thresholds:
			scores = [(1 if i>=threshold else 0) for i in predictions]
			temp_score = f1_score(labels,scores,average='weighted')
			if temp_score>best_wf1:
				best_threshold=threshold
				best_wf1 = temp_score
		print('best_threshold',best_threshold)
	else:
		best_threshold = arg_threshold
	cat_preds = [(1 if predictions[i]>=best_threshold else 0) for i in range(len(predictions)) if id_to_relation[features[i][1]]=='has_label']
	rel_preds = [(1 if predictions[i]>=best_threshold else 0) for i in range(len(predictions)) if id_to_relation[features[i][1]]!='has_label']
	if not dname=='':
		with open(dname,'w') as f:
			for sc in predictions: f.write('%f\n'%(sc))
	predictions = [(1 if i>=best_threshold else 0) for i in predictions]
	print('f1 score %0.2f | wf1 score %0.2f | precision score %0.2f | recall score %0.2f | label wf1 %0.2f | relation wf1 %0.2f '%(f1_score(labels,predictions),f1_score(labels,predictions,average='weighted'),precision_score(labels,predictions,average='weighted'),recall_score(labels,predictions,average='weighted'),f1_score(cat_labels,cat_preds,average='weighted'),f1_score(rel_labels,rel_preds,average='weighted')))
	if len(org_test_indices)!=0:
		print('f1 score on original test set %0.2f',f1_score([labels[i] for i in range(len(labels)) if i not in org_test_indices],[predictions[i] for i in range(len(predictions)) if i not in org_test_indices]))
	return best_threshold,best_wf1
def train(epoch,model,train_set,criterion,optimizer):
	loss_val = 0.0
	model.train(True)
	predictions = []
	all_labels = []
	for features,labels in tqdm(train_set):
		features,labels = Variable(features),Variable(labels)
		if use_cuda: 
			features,labels = features.cuda(),labels.cuda()
		output = model(features[:,0],features[:,1],features[:,2])
		predictions.extend(output.data.tolist())
		all_labels.extend(labels.data.tolist())
		loss = criterion(output,labels.float())
		loss.backward()
		optimizer.step()
		model.zero_grad()
		loss_val+=loss.item()
	print('epoch %d : loss %f'%(epoch+1,loss_val))	

def test(model,test_set,test_features,arg_threshold=None,org_test_indices=[],dname=''):
	model.train(False)
	predictions = []
	all_labels = []
	for features,labels in test_set:
		features = Variable(features)
		if use_cuda: 
			features = features.cuda()
		output = model(features[:,0],features[:,1],features[:,2])
		predictions.extend(output.data.tolist())
		all_labels.extend(labels.tolist())
	return evaluate(all_labels,predictions,test_features,arg_threshold=arg_threshold,org_test_indices=org_test_indices,dname=dname)

def evaluate_link_pred(model):
	fb15k_test=[i.rstrip() for i in open("../combined/data_orig_FB15k-237/test.txt")]
	fb15k_test_actual=[]
	missed_line=0
	for i in fb15k_test:
		l=i.rstrip().split("\t")
		fb15k_test_actual.append([entity_to_id[l[0]],relation_to_id[l[1]],entity_to_id[l[2]]])
	# print(missed_line)
	# exit()
	test_count=0
	# fb15k_test_actual=numpy.array(fb15k_test_actual, dtype='int64')
	# print(fb15k_test_actual)
	# exit()
	totals = { "m":{"mrr":0, "mr":0, "hits10":0, "hits1":0},"e2":{"mrr":0, "mr":0, "hits10":0, "hits1":0},"e1":{"mrr":0, "mr":0, "hits10":0, "hits1":0}}
	print("ok")
	fb15k_test_new=np.array(fb15k_test_actual, dtype='int64')
	# reverse_entity_map = {value:key for key, value in dict.items()}
	# ranker.scoring_function.sort_labels(kb.types)
	# exit()
	batch_size=50
	for i in range(0,int(fb15k_test_new.shape[0]),batch_size):
		start = i
		end = min(i+batch_size, fb15k_test_new.shape[0])
		s = fb15k_test_new[start:end, 0]
		r = fb15k_test_new[start:end, 1]
		o = fb15k_test_new[start:end, 2]
		knowns_o = get_knowns(s, r, flag_s_o=1)
		knowns_s = get_knowns(o, r, flag_s_o=0)
		print(knowns_o)
		# exit()
		s = torch.autograd.Variable(torch.from_numpy(s).cuda().unsqueeze(1), requires_grad=False)
		r = torch.autograd.Variable(torch.from_numpy(r).cuda().unsqueeze(1), requires_grad=False)
		o = torch.autograd.Variable(torch.from_numpy(o).cuda().unsqueeze(1), requires_grad=False)
		
		knowns_o = torch.from_numpy(knowns_o).cuda()
		knowns_s = torch.from_numpy(knowns_s).cuda()
		scores = model.test(s, r, None).data
		# print(scores.shape)
		# print(o.shape)
		score_of_expected = scores.gather(1, o.data)

		scores.scatter_(1, knowns_o, 0.0)
		greater = scores.ge(score_of_expected).float()
		equal = scores.eq(score_of_expected).float()
		rank = greater.sum(dim=1)+1+equal.sum(dim=1)/2.0
		ranks_o, scores_o, score_of_expected_o = rank, scores, score_of_expected

		# scores = model.test(None, r, o).data
		# # print(scores.shape)
		# # print(o.shape)
		# score_of_expected = scores.gather(1, s.data)

		# scores.scatter_(1, knowns_s, 0.0)
		# greater = scores.ge(score_of_expected).float()
		# equal = scores.eq(score_of_expected).float()
		# rank = greater.sum(dim=1)+1+equal.sum(dim=1)/2.0
		# ranks_s, scores_s, score_of_expected_s = rank, scores, score_of_expected

		# totals['e1']['mr'] += ranks_s.sum()
		# totals['e1']['mrr'] += (1.0/ranks_s).sum()
		# totals['e1']['hits10'] += ranks_s.le(11).float().sum()
		# totals['e1']['hits1'] += ranks_s.eq(1).float().sum()

		totals['e2']['mr'] += ranks_o.sum()
		totals['e2']['mrr'] += (1.0/ranks_o).sum()
		totals['e2']['hits10'] += ranks_o.le(11).float().sum()
		totals['e2']['hits1'] += ranks_o.eq(1).float().sum()

		# totals['m']['mr'] += (ranks_s.sum()+ranks_o.sum())/2.0
		# totals['m']['mrr'] += ((1.0/ranks_s).sum()+(1.0/ranks_o).sum())/2.0
		# totals['m']['hits10'] += (ranks_s.le(11).float().sum() + ranks_o.le(11).float().sum())/2.0
		# totals['m']['hits1'] += (ranks_s.eq(1).float().sum() + ranks_o.eq(1).float().sum())/2.0
		print(totals['e2']['mrr'])
	#print('my evaluation',name)
	#print(labels[:10],scores[:10])
	#print(name,eval_cnt,'auc',average_precision_score(labels,scores))
	totals['m'] = {x:totals['m'][x]/fb15k_test_new.shape[0] for x in totals['m']}
	totals['e2'] = {x:totals['e2'][x]/fb15k_test_new.shape[0] for x in totals['e2']}
	totals['e1'] = {x:totals['e1'][x]/fb15k_test_new.shape[0] for x in totals['e1']}
	print(totals)

	return totals

# def save_state(model):
# 	state = model.state_dict()
# 	torch.save(state, args.save_model)

def load_state(model):
	state = torch.load(args.save_model)
	model.load_state_dict(state)
	return model
if args.model=='ConvE':
	model = ConvE(len(entity_to_id),len(relation_to_id))
else : model = Complex(len(entity_to_id),len(relation_to_id),args.embed_size)
if use_cuda: 
	model = model.cuda()

# optimizer = optim.Adam(model.parameters(),lr=args.lr)
# criterion = BCELoss()
# best_threshold , best_wf1 = 0,0.0
# best_model = {}
# for epoch in range(args.epochs):
# 	train_loader = get_train_loader(train_features,neg_samples=args.neg_samples)
# 	train(epoch,model,train_loader,criterion,optimizer)
# 	print('Evaluation on valid set')
# 	epoch_thres,epoch_wf1 = test(model,valid_loader,valid_features)
# 	if epoch_wf1>best_wf1:
# 		best_threshold = epoch_thres
# 		best_wf1 = epoch_wf1
# 		save_state(model)
# 		print('Evaluation on test set')
# 		test(model,test_loader,test_features,arg_threshold=best_threshold,org_test_indices=org_test_indices)
	
# load model
model = load_state(model)
# print('best result on valid set')
# test(model,valid_loader,valid_features,arg_threshold=best_threshold)
print('Evaluation on test set with best model saved based on valid set')
evaluate_link_pred(model)


